# ==========================================================================
# Atlas — one-shot bootstrap: preflight, guard hooks, .env secrets, upstream
# checkouts, and a bring-up checklist. Idempotent; safe to re-run.
# ==========================================================================
set -Eeuo pipefail

say()  { printf '\033[1m%s\033[0m\n' "$*"; }
warn() { printf '\033[33mwarning: %s\033[0m\n' "$*" >&2; }
die()  { printf '\033[31merror: %s\033[0m\n' "$*" >&2; exit 1; }

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_DIR"

say "Atlas bootstrap"
say "==============="

# ---- 1. Preflight ----------------------------------------------------------
say "1/5 preflight"
command -v git      >/dev/null || die "git is required"
command -v docker   >/dev/null || die "docker is required"
docker compose version >/dev/null 2>&1 || die "the docker compose plugin is required"
command -v openssl  >/dev/null || die "openssl is required (secret generation)"
command -v curl     >/dev/null || die "curl is required"
say "    ok — git, docker, compose, openssl, curl"

# python3 is only needed when Cerulean Vault is configured (step 4 resolves the
# `vault://` references with it), so it is checked there rather than here.
# git is used for the guard hooks; there is no upstream clone step any more.

# ---- 2. Guard hooks --------------------------------------------------------
say "2/5 attribution guard hooks"
git config core.hooksPath .githooks
say "    ok — core.hooksPath -> .githooks"

# ---- 3. .env ---------------------------------------------------------------
say "3/5 environment"
if [ -f .env ]; then
  warn ".env already exists — leaving it untouched"
else
  cp .env.example .env
  # Replace change-me placeholders for secret-ish keys with random values.
  while IFS='=' read -r key value; do
    case "$key" in
      ''|\#*) continue ;;
    esac
    case "$key" in
      *PASSWORD*|*SECRET*|*KEY*|*TOKEN*)
        if [ -n "$value" ] && printf '%s' "$value" | grep -q '^change-me'; then
          sed -i "s|^${key}=.*|${key}=$(openssl rand -hex 24)|" .env
        fi
        ;;
    esac
  done < .env
  say "    ok — created .env with generated secrets (edit host/domain values)"
fi

# ---- 4. Cerulean Vault (secrets) -------------------------------------------
# Atlas is compose-and-images only: nothing in a running container resolves a
# `vault://` reference, and Compose cannot either. So the references in
# .env.example are resolved HERE, into the gitignored .env, and a reference that
# cannot be resolved stops the setup — an empty credential would surface later
# as an auth error naming the wrong service.
say "4/5 Cerulean Vault (SecretOps)"
vault_refs="$(grep -cE '^[A-Za-z_][A-Za-z0-9_]*=vault://' .env 2>/dev/null || true)"

vault_ready=0
if [ -n "${VAULT_ADDR:-}" ] && { [ -n "${VAULT_TOKEN:-}" ] || [ -f "${VAULT_TOKEN_FILE:-}" ]; }; then
  vault_ready=1
fi

if [ "${vault_refs:-0}" -gt 0 ] && [ "$vault_ready" = 1 ]; then
  command -v python3 >/dev/null || die "python3 is required to resolve vault:// references"
  # Seed this stack's generated secrets first (idempotent — an existing key is
  # never rotated by a re-run), then materialize every reference.
  python3 scripts/vault-bootstrap.py || die "Vault bootstrap failed (see above)"
  python3 scripts/vault-resolve.py --file .env --write \
    || die "a vault:// reference did not resolve — .env left untouched"
  say "    ok — ${vault_refs} reference(s) resolved from Cerulean Vault"
elif [ "${vault_refs:-0}" -gt 0 ]; then
  # Vault not configured: keep the stack bringable-up on a dev box by generating
  # the keys this stack owns. The Authentik-issued secret stays empty (nothing
  # local can invent a value Authentik has to agree with).
  for key in GITEA_DB_PASSWORD CONVEX_INSTANCE_SECRET; do
    if grep -qE "^${key}=vault://" .env; then
      sed -i "s|^${key}=.*|${key}=$(openssl rand -hex 24)|" .env
    fi
  done
  warn "VAULT_ADDR is not set — generated local secrets for GITEA_DB_PASSWORD and"
  warn "CONVEX_INSTANCE_SECRET instead of reading Cerulean Vault."
  warn "Point VAULT_ADDR/VAULT_TOKEN (or VAULT_TOKEN_FILE) at Vault and re-run, or run"
  warn "scripts/vault-resolve.py --write once the generated secrets are in Vault."
else
  say "    ok — no vault:// references in .env"
fi

# ---- 5. Checklist ----------------------------------------------------------
# There is no upstream checkout any more: the `chef` profile used to clone
# get-convex/chef into services/chef at this step, and Chef is retired as a
# builder (convergence plan §2/§8 — one builder, and it is Olympus's engine).
# A checkout that still has services/chef is left untouched and unused.
if [ -d services/chef ]; then
  warn "services/chef is present from the retired Chef profile — nothing reads it"
  warn "(Atlas no longer runs a builder; see docs/stack.md)"
fi

say "5/5 next steps"
printf '%s\n' \
  "  1. Core platform (Gitea + Convex): make up" \
  "  2. Model gateway:                  make gateway-check (shared OmniRoute on Zeus — Group 2)" \
  "  3. Convex admin key:               make convex-key" \
  "  4. Full runbook:                   docs/Deployment.md"

say "done."
