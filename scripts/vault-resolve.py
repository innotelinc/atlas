#!/usr/bin/env python3
"""Resolve ``vault://`` references against Cerulean Vault (KV v2).

Atlas is compose-and-images only: nothing in it can resolve a reference at
runtime the way ONYX's Go services or Distro's Node services do. So the
resolution point is **setup**, which is what this script is for.

``scripts/setup.sh`` generates Atlas's ``.env`` from ``.env.example`` — which
carries ``vault://<mount>/<path>#<key>`` references for the secrets Cerulean
Vault owns — and then calls this script so the stack never starts holding a
literal reference string where a credential belongs. Compose cannot resolve a
reference either, so the resolved value is written into the gitignored ``.env``
and the reference in ``.env.example`` stays the tracked source of truth.

A reference that cannot be resolved is a **hard failure**: exiting non-zero with
an empty credential is worse than stopping, because the failure surfaces later
as an authentication error that names the wrong thing.

Usage::

    python3 scripts/vault-resolve.py --check                  # what would resolve
    python3 scripts/vault-resolve.py --write                  # materialize into .env
    python3 scripts/vault-resolve.py --file .env --write
    python3 scripts/vault-resolve.py 'vault://cerulean/atlas#GITEA_DB_PASSWORD'

The last form prints the secret itself (for piping into one consumer) — every
other form prints **key names only**, never values.

Every address and credential comes from the environment:

    VAULT_ADDR          e.g. http://vault:8200
    VAULT_TOKEN         (or VAULT_TOKEN_FILE) the path-scoped ``atlas`` token
    VAULT_PREFIX        KV v2 mount point (default: cerulean)
    VAULT_NAMESPACE     Enterprise namespaces; unused on OSS Vault
    VAULT_SKIP_VERIFY   "1" to accept a self-signed certificate
    VAULT_CACERT        CA bundle for TLS
"""
from __future__ import annotations

import argparse
import json
import os
import ssl
import sys
import urllib.error
import urllib.request
from pathlib import Path

DEFAULT_PREFIX = "cerulean"
REFERENCE_SCHEME = "vault://"
DEFAULT_ENV_FILE = ".env"


def fail(message: str) -> "None":
    sys.exit(f"{message}\n")


def read_token() -> str:
    """VAULT_TOKEN, else VAULT_TOKEN_FILE — the same order the Vault CLI uses."""
    direct = os.environ.get("VAULT_TOKEN", "").strip()
    if direct:
        return direct

    token_file = os.environ.get("VAULT_TOKEN_FILE", "").strip()
    if not token_file:
        fail(
            "No Vault token. Set VAULT_TOKEN, or VAULT_TOKEN_FILE to a file containing one.\n"
            "This stack's path-scoped token lives at ./data/vault/token/atlas.token\n"
            "(the `atlas` policy); see the Secrets section of docs/stack.md."
        )

    try:
        token = Path(token_file).read_text(encoding="utf-8").strip()
    except OSError as error:
        fail(f"Could not read VAULT_TOKEN_FILE ({token_file}): {error.strerror}")

    if not token:
        fail(f"VAULT_TOKEN_FILE ({token_file}) is empty.")
    return token


def parse_reference(value: str) -> tuple[str, str, str] | None:
    """``vault://<mount>/<path>#<key>`` → (mount, path, key), or None.

    The ``#key`` fragment is required: a reference without one names a whole
    secret, and a consumer that needs one value cannot guess which.
    """
    if not value.startswith(REFERENCE_SCHEME):
        return None

    rest = value[len(REFERENCE_SCHEME) :]
    if "#" not in rest:
        return None
    location, _, key = rest.partition("#")
    mount, _, path = location.partition("/")
    if not mount or not path or not key:
        return None
    return mount, path, key


def is_reference(value: str) -> bool:
    return parse_reference(value) is not None


class Vault:
    """The two calls this script needs, with TLS and namespace handled once."""

    def __init__(self) -> None:
        addr = os.environ.get("VAULT_ADDR", "").strip()
        if not addr:
            fail(
                "VAULT_ADDR is not set, so no `vault://` reference can be resolved.\n"
                "Either point it at Cerulean Vault (scripts/vault-bootstrap.py seeds\n"
                "this stack's generated secrets) or remove the references from .env."
            )
        self.addr = addr.rstrip("/")
        self.token = read_token()
        self.namespace = os.environ.get("VAULT_NAMESPACE", "").strip()

        self._verify: ssl.SSLContext | bool = True
        if os.environ.get("VAULT_SKIP_VERIFY", "").strip() in ("1", "true", "yes"):
            self._verify = ssl._create_unverified_context()
        elif os.environ.get("VAULT_CACERT", "").strip():
            self._verify = ssl.create_default_context(cafile=os.environ["VAULT_CACERT"].strip())

        # One read per path, not per key: a secret holding three referenced keys
        # is one request, and a config with a dozen references stays one round
        # trip per *secret*.
        self._cache: dict[str, dict[str, str]] = {}

    def _api(self, path: str) -> tuple[int, dict]:
        request = urllib.request.Request(f"{self.addr}/v1/{path.lstrip('/')}", method="GET")
        request.add_header("X-Vault-Token", self.token)
        request.add_header("Accept", "application/json")
        if self.namespace:
            request.add_header("X-Vault-Namespace", self.namespace)

        try:
            with urllib.request.urlopen(request, timeout=30, context=self._verify) as response:
                payload = response.read()
                return response.status, (json.loads(payload) if payload else {})
        except urllib.error.HTTPError as error:
            detail = error.read().decode(errors="replace").strip()[:200]
            return error.code, {"errors": detail}
        except urllib.error.URLError as error:
            fail(
                f"Could not reach Vault at {self.addr}: {error.reason}\n"
                "Check VAULT_ADDR, and that the server is unsealed."
            )

    def secret(self, mount: str, path: str) -> dict[str, str]:
        cache_key = f"{mount}/{path}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        status, body = self._api(f"{mount}/data/{path}")
        if status == 404:
            fail(
                f"{cache_key} is not in Vault.\n"
                "Seed this stack's generated secrets with:\n"
                "  python3 scripts/vault-bootstrap.py\n"
                "and store the Authentik-issued one with:\n"
                "  python3 scripts/vault-migrate.py --from-env-file .env --keys OIDC_CLIENT_SECRET"
            )
        if status != 200:
            fail(f"Reading {cache_key} failed: HTTP {status} — {body.get('errors')}")

        outer = body.get("data") if isinstance(body, dict) else None
        if not isinstance(outer, dict) or not isinstance(outer.get("data"), dict):
            fail(
                f"{mount}/ is not answering as KV v2 (the read returned no data.data nesting).\n"
                f"Point VAULT_PREFIX at the KV v2 mount (Cerulean's default is `{DEFAULT_PREFIX}`)."
            )

        self._cache[cache_key] = outer["data"]
        return outer["data"]

    def resolve(self, reference: str) -> str:
        parsed = parse_reference(reference)
        if parsed is None:
            fail(
                f"Not a Vault reference: {reference}\n"
                "Expected vault://<mount>/<path>#<key>."
            )
        mount, path, key = parsed
        secret = self.secret(mount, path)
        if key not in secret:
            fail(f"{mount}/{path} has no key {key} (present: {', '.join(sorted(secret))}).")
        value = secret[key]
        if not isinstance(value, str) or not value:
            fail(f"{mount}/{path}#{key} is empty — refusing to hand back an empty credential.")
        return value


def split_env_line(line: str) -> tuple[str, str, str] | None:
    """(indent + key, separator, raw value) for a KEY=VALUE line, else None.

    Deliberately shallow: this reads the same shape Compose does and must not
    rewrite a line it did not positively identify as an assignment.
    """
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return None
    if "=" not in line:
        return None

    before, _, after = line.partition("=")
    key = before.strip()
    if not key or any(character.isspace() for character in key):
        return None
    return before, "=", after


def unquote(value: str) -> tuple[str, str, str]:
    """(inner value, quote prefix, trailing comment) for one raw value."""
    trimmed = value.strip()
    for quote in ('"', "'"):
        if trimmed.startswith(quote) and trimmed.endswith(quote) and len(trimmed) >= 2:
            return trimmed[1:-1], quote, ""
    # Unquoted: drop a trailing comment the way Compose does.
    marker = trimmed.find(" #")
    if marker != -1:
        return trimmed[:marker].strip(), "", trimmed[marker:]
    return trimmed, "", ""


def resolve_file(path: Path, write: bool) -> int:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as error:
        fail(f"Could not read {path}: {error.strerror}")

    rewritten: list[str] = []
    names: list[str] = []
    # Built on first use, not up front: a checkout with no references must not
    # need Vault configured to report that it has none.
    vault = None

    for line in text.split("\n"):
        parts = split_env_line(line)
        if parts is None:
            rewritten.append(line)
            continue

        prefix, separator, raw = parts
        reference, quote, comment = unquote(raw)
        if not is_reference(reference):
            rewritten.append(line)
            continue

        # Resolved in both modes: `--check` proves the reference reads back, and
        # `--write` is the same read with the value kept.
        if vault is None:
            vault = Vault()
        value = vault.resolve(reference)
        names.append(prefix.strip())

        rewritten.append(line if not write else f"{prefix}{separator}{quote}{value}{quote}{comment}")

    if not names:
        print(f"--- {path}: no vault:// references ---")
        return 0

    if write:
        # Write beside the target and rename: a crash mid-write leaves the
        # previous .env intact instead of a half-resolved one.
        temporary = path.with_name(f".{path.name}.vault-resolve.tmp")
        temporary.write_text("\n".join(rewritten), encoding="utf-8")
        temporary.chmod(0o600)
        os.replace(temporary, path)
        print(f"--- {path}: resolved {len(names)} reference(s) into values ---")
    else:
        print(f"--- {path}: {len(names)} reference(s) resolve ---")

    for name in names:
        print(f"    {name}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Resolve vault:// references against Cerulean Vault (KV v2).",
    )
    parser.add_argument("reference", nargs="?", help="a single vault:// reference to print")
    parser.add_argument("--file", default=DEFAULT_ENV_FILE, help="env file (default: .env)")
    parser.add_argument("--check", action="store_true", help="resolve, report, write nothing")
    parser.add_argument("--write", action="store_true", help="materialize references in place")
    args = parser.parse_args()

    if args.reference and (args.check or args.write):
        fail("Give either a reference or --file, not both.")
    if args.check and args.write:
        fail("--check and --write are mutually exclusive.")

    if args.reference:
        print(Vault().resolve(args.reference))
        return 0

    return resolve_file(Path(args.file), write=args.write)


if __name__ == "__main__":
    sys.exit(main())
