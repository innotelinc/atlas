#!/usr/bin/env python3
"""Store this stack's generated secrets in Cerulean Vault (HashiCorp Vault, KV v2).

Cerulean is the platform's SecretOps layer: a durable, file-backed Vault with
KV v2 mounted at ``VAULT_PREFIX`` and a periodic token scoped to this stack's
own path under it (the ``atlas`` policy — see docs/stack.md). This script writes
Atlas's *generated* secrets there, so they stop living in a plaintext ``.env``.

It mirrors ``olympus/scripts/vault-bootstrap.py`` — the reference
implementation of this pattern — with one difference: Olympus writes a single
generated password, Atlas has three generated secrets, so the write is a
**union** rather than a replace. A second run reports what is already in sync
and writes nothing.

Which keys it will invent, and which it will not:

* ``GITEA_DB_PASSWORD``      generated here (the Gitea/Postgres password)
* ``CONVEX_INSTANCE_SECRET`` generated here (Convex's instance secret)

* ``OIDC_CLIENT_SECRET``     issued by Cerulean Authentik — **never invented**

The last one is a credential two systems have to agree on, so a locally random
value would be a wrong value that looks like a working one. Store it from
whatever Authentik printed, with the shared migrator::

    python3 scripts/vault-migrate.py --from-env-file .env --keys OIDC_CLIENT_SECRET

(``CHEF_SESSION_SECRET`` and ``CHEF_OIDC_CLIENT_SECRET`` used to be on those two
lists. They went with the retired `chef` profile — see docs/stack.md.)

Every address and credential comes from the environment — nothing is hardcoded
here, because this file is tracked in a public repository.

Required:
    VAULT_ADDR          e.g. http://vault:8200
    VAULT_TOKEN         a token with write access to VAULT_PATH — the
                        path-scoped ``atlas`` policy, NOT the platform's
                        mount-wide ``cerulean`` one
                        (or VAULT_TOKEN_FILE, pointing at one; Vault's own
                        convention, so `vault login` output can be reused)
    VAULT_PREFIX        KV v2 mount point (Cerulean default: cerulean)

Optional:
    VAULT_PATH          path under the mount (default: atlas)
    VAULT_NAMESPACE     Enterprise namespaces; unused on OSS Vault
    VAULT_SKIP_VERIFY   "1" to accept a self-signed certificate
    VAULT_CACERT        CA bundle for TLS

Once written, ``.env`` may carry a reference instead of the value::

    GITEA_DB_PASSWORD=vault://cerulean/atlas#GITEA_DB_PASSWORD

which is exactly the ``vault://<mount>/<path>#<key>`` convention Cerulean
resolves at startup, so the stack and the platform agree on one format.
"""
from __future__ import annotations

import json
import os
import secrets
import ssl
import string
import sys
import urllib.error
import urllib.request
from pathlib import Path

DEFAULT_PREFIX = "cerulean"
DEFAULT_PATH = "atlas"

#: Secrets this script may generate. Values are what a reader should expect.
GENERATED_KEYS = (
    "GITEA_DB_PASSWORD",
    "CONVEX_INSTANCE_SECRET",
)

#: Secrets that must come from somewhere else. Listed so the report is honest
#: about what is still missing instead of looking complete after one write.
EXTERNAL_KEYS = ("OIDC_CLIENT_SECRET",)

KEY_BYTES = 24


def fail(message: str) -> "None":
    sys.exit(f"{message}\n")


def require(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        fail(
            f"{name} is not set. Export it (or load your .env) before running this script.\n"
            "See the module docstring for the full list."
        )
    return value


def read_token() -> str:
    """VAULT_TOKEN, else VAULT_TOKEN_FILE — the same order the Vault CLI uses."""
    direct = os.environ.get("VAULT_TOKEN", "").strip()
    if direct:
        return direct

    token_file = os.environ.get("VAULT_TOKEN_FILE", "").strip()
    if not token_file:
        fail(
            "No Vault token. Set VAULT_TOKEN, or VAULT_TOKEN_FILE to a file containing one.\n"
            "On the Cerulean platform this stack's path-scoped token lives at\n"
            "./data/vault/token/atlas.token (the `atlas` policy); see the\n"
            "Secrets section of docs/stack.md for how it is minted and renewed."
        )

    try:
        token = Path(token_file).read_text(encoding="utf-8").strip()
    except OSError as error:
        fail(f"Could not read VAULT_TOKEN_FILE ({token_file}): {error.strerror}")

    if not token:
        fail(f"VAULT_TOKEN_FILE ({token_file}) is empty.")
    return token


ADDR = require("VAULT_ADDR").rstrip("/")
TOKEN = read_token()
PREFIX = (os.environ.get("VAULT_PREFIX", "").strip() or DEFAULT_PREFIX).strip("/")
SECRET_PATH = (os.environ.get("VAULT_PATH", "").strip() or DEFAULT_PATH).strip("/")
NAMESPACE = os.environ.get("VAULT_NAMESPACE", "").strip()

_verify: ssl.SSLContext | bool = True
if os.environ.get("VAULT_SKIP_VERIFY", "").strip() in ("1", "true", "yes"):
    _verify = ssl._create_unverified_context()
elif os.environ.get("VAULT_CACERT", "").strip():
    _verify = ssl.create_default_context(cafile=os.environ["VAULT_CACERT"].strip())


def api(method: str, path: str, body: dict | None = None) -> tuple[int, dict]:
    """Call Vault. Returns (status, parsed-body); never logs the token."""
    url = f"{ADDR}/v1/{path.lstrip('/')}"
    data = json.dumps(body).encode() if body is not None else None

    request = urllib.request.Request(url, data=data, method=method)
    request.add_header("X-Vault-Token", TOKEN)
    request.add_header("Accept", "application/json")
    if data is not None:
        request.add_header("Content-Type", "application/json")
    if NAMESPACE:
        request.add_header("X-Vault-Namespace", NAMESPACE)

    try:
        with urllib.request.urlopen(request, timeout=30, context=_verify) as response:
            payload = response.read()
            return response.status, (json.loads(payload) if payload else {})
    except urllib.error.HTTPError as error:
        detail = error.read().decode(errors="replace").strip()
        try:
            detail = json.dumps(json.loads(detail).get("errors", detail))[:200]
        except Exception:
            detail = detail[:200]
        return error.code, {"errors": detail}
    except urllib.error.URLError as error:
        fail(
            f"Could not reach Vault at {ADDR}: {error.reason}\n"
            "Check VAULT_ADDR, and that the server is unsealed."
        )


def is_kv2_envelope(body: object) -> bool:
    """KV v2 nests the payload under data.data; KV v1 stops at data."""
    if not isinstance(body, dict):
        return False
    outer = body.get("data")
    return isinstance(outer, dict) and isinstance(outer.get("data"), dict)


def probe_kv2() -> None:
    """Verify the mount through the ONE path this token was granted.

    A scoped token cannot read sys/mounts — that endpoint is cluster-wide — and it
    should not be able to list the mount root either, since that would disclose
    every sibling key's name. So the only honest probe is the path we are about to
    use: a 200 or a 404 both prove the KV v2 *data* endpoint is served, and 403
    means the grant is wrong.

    The version itself cannot be settled by a 404 (an uncreated v2 path and a v1
    mount look identical), so the write's own response settles it.
    """
    status, body = api("GET", f"{PREFIX}/data/{SECRET_PATH}")
    if status in (200, 404):
        print(f"--- {PREFIX}/data/{SECRET_PATH} is served (KV v2 data endpoint) ---")
        return
    if status == 403:
        fail(
            f"The token cannot read {PREFIX}/data/{SECRET_PATH}.\n"
            f"Grant it a policy covering {PREFIX}/data/{SECRET_PATH} "
            f"and {PREFIX}/metadata/{SECRET_PATH}, then re-run."
        )
    fail(f"Could not reach {PREFIX}/data/{SECRET_PATH}: HTTP {status} — {body.get('errors')}")


def ensure_kv2() -> None:
    """KV v2 must be mounted at PREFIX. Create it if absent, verify if present."""
    status, mounts = api("GET", "sys/mounts")
    if status == 403:
        # Scoped token: cannot see the cluster's mount table. Verify instead
        # through the prefix we were actually granted.
        print(f"--- sys/mounts is not readable with this token (scoped) — probing {PREFIX}/ ---")
        probe_kv2()
        return
    if status != 200:
        fail(f"Reading sys/mounts failed: HTTP {status} — {mounts.get('errors')}")

    existing = (mounts.get("data") or mounts).get(f"{PREFIX}/")
    if existing is None:
        print(f"--- enabling KV v2 at {PREFIX}/ ---")
        status, created = api(
            "POST", f"sys/mounts/{PREFIX}", {"type": "kv", "options": {"version": "2"}}
        )
        if status not in (200, 204):
            fail(f"Could not enable KV v2 at {PREFIX}/: HTTP {status} — {created.get('errors')}")
        print(f"    enabled {PREFIX}/ as KV v2")
        return

    version = str((existing.get("options") or {}).get("version", "1"))
    if version != "2":
        fail(
            f"{PREFIX}/ is mounted as KV v{version}, not v2.\n"
            "KV v1 has no versioning or metadata; enable KV v2 at a different prefix\n"
            f"(VAULT_PREFIX) or migrate the mount."
        )
    print(f"--- {PREFIX}/ is KV v2 ---")


def read_secret() -> dict[str, str]:
    """The secret as it stands, or an empty map when it does not exist yet.

    A missing path is the normal first run, not an error. Anything else that is
    not a KV v2 read is, because reading it wrong is how this script would
    overwrite keys it cannot see.
    """
    status, body = api("GET", f"{PREFIX}/data/{SECRET_PATH}")
    if status == 404:
        return {}
    if status != 200:
        fail(f"Reading {PREFIX}/{SECRET_PATH} failed: HTTP {status} — {body.get('errors')}")
    if not is_kv2_envelope(body):
        fail(
            f"{PREFIX}/ is not answering as KV v2 (the read returned no data.data nesting).\n"
            "KV v1 has no versioning and cannot hold secrets the way this stack expects.\n"
            f"Point VAULT_PREFIX at the KV v2 mount (Cerulean's default is `cerulean`)."
        )
    return ((body.get("data") or {}).get("data") or {})


def generate() -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(KEY_BYTES))


def main() -> int:
    print(f"Vault:  {ADDR}")
    print(f"  mount: {PREFIX}/  path: {SECRET_PATH}  token: {len(TOKEN)} chars")
    print(f"  generated here: {', '.join(GENERATED_KEYS)}")
    print(f"  must be provided: {', '.join(EXTERNAL_KEYS)}")

    ensure_kv2()

    # /v1/status is unauthenticated and 200 only while unsealed.
    status, sealed = api("GET", "sys/seal-status")
    if status == 200 and sealed.get("sealed"):
        fail("Vault is sealed. Unseal it first (scripts/vault-entrypoint.sh does this on start).")

    existing = read_secret()

    # Union, not replace: a key already in Vault is preserved untouched, so a
    # re-run cannot rotate a credential a running service is using.
    payload = dict(existing)
    created: list[str] = []
    for key in GENERATED_KEYS:
        current = str(payload.get(key, "")).strip()
        # A reference is not a secret to copy — it names where a secret lives,
        # and writing it back would replace the value with the pointer.
        if current and not current.startswith(("vault://", "infisical://")):
            continue
        payload[key] = generate()
        created.append(key)

    missing = [k for k in EXTERNAL_KEYS if not str(payload.get(k, "")).strip()]

    if not created and not missing:
        print(f"\n--- {PREFIX}/{SECRET_PATH} is already in sync — nothing written ---")
    if not created:
        if missing:
            print(f"\n--- nothing to generate; still missing: {', '.join(missing)} ---")
            print("    store the remaining key(s) from what Authentik issued:")
            print(
                "      python3 scripts/vault-migrate.py --from-env-file .env \\\n"
                f"          --keys {','.join(EXTERNAL_KEYS)}"
            )
        return 0

    print(f"--- writing {len(payload)} key(s) to {PREFIX}/{SECRET_PATH} ---")
    print(f"    generated: {', '.join(created)}")
    status, written = api(
        "POST",
        f"{PREFIX}/data/{SECRET_PATH}",
        {"data": payload},
    )
    if status not in (200, 204):
        fail(f"Writing the secret failed: HTTP {status} — {written.get('errors')}")
    # A KV v2 write answers with the new version number; KV v1 has no versioning
    # and answers with nothing. (Only *reads* nest the payload under data.data.)
    outer = written.get("data") if isinstance(written, dict) else None
    if not isinstance(outer, dict) or "version" not in outer:
        fail(
            f"{PREFIX}/ did not answer as KV v2 (the write returned no version).\n"
            "KV v1 has no versioning and cannot hold secrets the way this stack expects.\n"
            f"Point VAULT_PREFIX at the KV v2 mount (Cerulean's default is `cerulean`)."
        )
    print(f"    stored (version {outer.get('version')}), values not printed")

    # Prove it round-trips before claiming success.
    read = read_secret()
    if read != payload:
        drift = sorted(set(payload) ^ set(read)) or sorted(
            k for k in payload if payload[k] != read.get(k)
        )
        fail(f"The secret did not read back identically; differing keys: {', '.join(drift)}")
    print(f"    verified: keys present = {sorted(read)}")

    if missing:
        print(f"\n--- still missing (issued elsewhere, never invented): {', '.join(missing)} ---")
        print("    store the remaining key(s) from what Authentik issued:")
        print(
            "      python3 scripts/vault-migrate.py --from-env-file .env \\\n"
            f"          --keys {','.join(EXTERNAL_KEYS)}"
        )

    print("\nReference them from .env instead of pasting the value:")
    for key in sorted(read):
        print(f"  {key}=vault://{PREFIX}/{SECRET_PATH}#{key}")
    print(f"\nVerify: curl -H \"X-Vault-Token: $VAULT_TOKEN\" {ADDR}/v1/{PREFIX}/data/{SECRET_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
