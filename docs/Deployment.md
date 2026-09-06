# Atlas — Deployment

Atlas runs as one Compose project on a single host, or split across hosts
behind the shared edge. Public hosts default to `git.innotel.us` (Gitea),
`chef.innotel.us` (Chef), and `convex.innotel.us` (Convex backend when apps
go live); every value is env-driven.

## Prerequisites

- Docker Engine with the Compose plugin, git, openssl, curl.
- Platform services reachable: Cerulean Authentik (`auth.cerulean.innotel.us`)
  for SSO, Infisical for secrets, Cerulean DNS/TLS + NPM Edge for hosts.
- For a dedicated Atlas host: a DNS pointer for `git.innotel.us` (CNAME to
  the apex) already provisioned through Cerulean.

## Stage 0 — Bootstrap

```bash
git clone https://github.com/innotelinc/atlas.git
cd atlas
./setup.sh        # guard hooks, .env with generated secrets, clones Chef
```

Edit `.env`: hosts, `GITEA_DB_PASSWORD`, `CONVEX_INSTANCE_SECRET`, OIDC
credentials, SMTP. Re-run anytime; it is idempotent.

## Stage 1 — Gitea + Convex (core)

```bash
make up            # docker compose up -d
make ps            # gitea, gitea-db, convex, convex-dashboard healthy
```

- **First boot — Gitea admin.** Open `http://<host>:3000` (or the edge URL
  below once provisioned) and complete the install screen, or create the
  admin headlessly:
  ```bash
  docker compose exec gitea gitea admin user create \
    --admin --username "$ATLAS_ADMIN_USER" --email "$ATLAS_ADMIN_EMAIL" \
    --random-password --must-change-password
  ```
- **Convex admin key:**
  ```bash
  make convex-key
  # paste into .env as CONVEX_SELF_HOSTED_ADMIN_KEY
  ```

## Stage 2 — Edge (Cerulean DNS + TLS + NPM hosts)

Following the platform convention (one wildcard cert per platform zone,
DNS-01 via the shared BIND; CNAMEs to the apex), provision:

| Host | Forward | Upstream (host port) |
| --- | --- | --- |
| `git.innotel.us` | NPM proxy host | `127.0.0.1:${GITEA_HTTP_PORT:-3000}` |
| `chef.innotel.us` | NPM proxy host | `127.0.0.1:${CHEF_PORT:-4310}` |
| `convex.innotel.us` | NPM proxy host | `127.0.0.1:${CONVEX_BACKEND_PORT:-3210}` |

`*.innotel.us` does not cover these hostnames' needs for deeper aliases —
issue per-zone wildcards (e.g. `*.git.innotel.us`) or exact-match per-host
certs exactly as the platform convention describes. Websocket/SSH upgrades
for Gitea go through the same proxy (NPM `websocket_support: true`).

## Stage 3 — OmniRoute (model gateway)

OmniRoute is the **single** model gateway in the platform and runs on Zeus
(Group 2 of the mesh, `10.10.2.1:20128`). Atlas does **not** run its own
instance — Chef reaches the shared gateway over the WireGuard mesh:

```env
OMNIROUTE_BASE_URL=http://10.10.2.1:20128/v1
OMNIROUTE_API_KEY=<key created in the Zeus OmniRoute dashboard>
```

```bash
make gateway-check   # verifies the mesh gateway is reachable
```

If Zeus is down, Atlas model calls fail — start Group 2 first (`./stack.sh
up 2` from the innotel-platform-stack repo).

## Stage 4 — Chef (AI app builder)

```bash
make chef-up       # docker compose --profile chef up -d --build
```

Chef runs from upstream source (`services/chef`). Two operating modes:

1. **Local-dev mode (default, upstream auth):** Chef's login uses the Convex
   hosted control plane — fine for a single operator or LAN use.
2. **Fully self-hosted (Authentik fork):** apply the documented auth fork
   (see [Integrations.md](Integrations.md) — *Auth fork*) so Chef logs in
   through Cerulean's Authentik, clear `VITE_PROVISION_HOST`/`BIG_BRAIN_HOST`,
   then rebuild. This is the production target and the point where generated
   apps deploy straight to Atlas Convex and land in Gitea.

## Stage 5 — Actions CI (optional)

Register a runner for Gitea Actions:

```bash
docker run -d --name atlas-runner --restart unless-stopped \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v atlas-runner:/data \
  -e GITEA_INSTANCE_URL=https://git.innotel.us \
  -e GITEA_RUNNER_REGISTRATION_TOKEN="<token from git.innotel.us/admin/runners>" \
  gitea/act_runner:latest
```

## Production notes

- **Persistence:** all state lives on named volumes (`gitea-data`,
  `gitea-db-data`, `convex-data`). Back them up — or point Convex at
  Postgres/S3 per upstream docs for managed durability.
- **Convex versions:** pin `CONVEX_VERSION` (and `GITEA_VERSION`) to a
  concrete release for reproducibility instead of `latest`.
- **Same-host coexistence:** other platforms bind port 3000 etc.; change
  `GITEA_HTTP_PORT`/`GITEA_SSH_PORT`/`CONVEX_*`/`CHEF_PORT` in `.env` and
  re-provision the NPM forwards — no code changes.
- **Secrets:** `.env` is derived from Infisical; rotate provider keys in the
  OmniRoute dashboard, never in code.
- **Unified vs split:** this compose runs standalone on its own server or as
  part of an all-encompassing stack — only `.env` (forward addresses/ports)
  and edge provisioning differ (see the platform stack README).
