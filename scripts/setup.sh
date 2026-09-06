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

# ---- 4. Upstream checkouts -------------------------------------------------
say "4/5 upstream checkouts (gitignored under services/)"
if [ -d services/chef/.git ]; then
  warn "services/chef already cloned — leaving it untouched"
else
  git clone --depth 1 https://github.com/get-convex/chef.git services/chef
  say "    ok — Chef (get-convex/chef) -> services/chef"
fi

# ---- 5. Checklist ----------------------------------------------------------
say "5/5 next steps"
printf '%s\n' \
  "  1. Core platform (Gitea + Convex): make up" \
  "  2. Model gateway:                  make gateway-check (shared OmniRoute on Zeus — Group 2)" \
  "  3. Convex admin key:               make convex-key" \
  "  4. Chef (AI app builder):          make chef-up  (see docs/Deployment.md — Stage 4)" \
  "  5. Full runbook:                   docs/Deployment.md"

say "done."
