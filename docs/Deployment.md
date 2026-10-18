# Atlas — Deployment

Atlas runs as one Compose project on a single host, or split across hosts
behind the shared edge. Public hosts default to `git.innotel.us` (Gitea) and
`convex.innotel.us` (Convex backend when apps go live); every value is
env-driven. The builder is **not** a host of this stack — it is Genie at
`genie.innotel.us`, and its connection to this forge is [genie.md](genie.md).

## Prerequisites

- Docker Engine with the Compose plugin, git, openssl, curl.
- Platform services reachable: Cerulean (`auth.cerulean.innotel.us`) for
  Authentik SSO + DNS/TLS + NPM Edge hosts, Cerulean Vault for secrets,
  Magnate (`magnate.innotel.us`) for paid developer-seat billing (optional).
- For a dedicated Atlas host: a DNS pointer for `git.innotel.us` (CNAME to
  the apex) already provisioned through Cerulean.

## Stage 0 — Bootstrap

```bash
git clone https://github.com/innotelinc/atlas.git
cd atlas
./setup.sh        # guard hooks, .env with generated secrets, clones Chef
```

Edit `.env`: hosts, OIDC credentials, SMTP. Re-run anytime; it is idempotent.

The secret keys are `vault://` references resolved by `setup.sh`: with
`VAULT_ADDR` + `VAULT_TOKEN` (or `VAULT_TOKEN_FILE`) set, it seeds the keys Atlas
generates (`scripts/vault-bootstrap.py`) and materializes every reference from
Cerulean Vault; without them it generates the three local secrets so a dev box
still comes up. `make vault-check` verifies the references resolve, `make
vault-sync` re-materializes after a rotation.

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
| `convex.innotel.us` | NPM proxy host | `127.0.0.1:${CONVEX_BACKEND_PORT:-3210}` |

`atlas.innotel.us` points at the same Gitea proxy host, so either name works as
`AGENT_ATLAS_URL` on Genie's side. `chef.innotel.us` is gone with the retired
Chef profile.

`*.innotel.us` does not cover these hostnames' needs for deeper aliases —
issue per-zone wildcards (e.g. `*.git.innotel.us`) or exact-match per-host
certs exactly as the platform convention describes. Websocket/SSH upgrades
for Gitea go through the same proxy (NPM `websocket_support: true`).

## Stage 3 — OmniRoute (model gateway)

OmniRoute is the **single** model gateway in the platform (Group 2 of the mesh —
`2-voice/`, on the Cerulean/trust host `192.168.1.71`). Atlas does **not** run its
own instance, and only Atlas's own probes and any app pointed at the gateway
consume it. Atlas dials the gateway's OpenAI-compatible endpoint on the address
that host publishes; an unauthenticated request answers `401`, which is the
gateway asking for the key in `OMNIROUTE_API_KEY` rather than an outage.

```env
OMNIROUTE_BASE_URL=http://192.168.1.71:20128/v1
OMNIROUTE_API_KEY=<key created in the Zeus OmniRoute dashboard>
```

```bash
make gateway-check   # verifies the mesh gateway is reachable
```

If Zeus is down, Atlas model calls fail — start Group 2 first (`./stack.sh
up 2` from the `ips` repo).

> **Shared with Distro.** Distro runs its own OmniRoute gateway in its compose
> stack (Group 5, Server 5) but points at the same upstream provider pool.
> Rotate provider keys once in the Zeus OmniRoute dashboard.

## Stage 3b — Magnate (billing, optional)

Atlas can gate paid developer seats via Magnate (RevenueOps). Set in `.env`:

```env
MAGNATE_URL=https://magnate.innotel.us
ENTITLEMENTS_API_TOKEN=<must equal Magnate's ENTITLEMENTS_API_TOKEN>
```

Magnate is Cerulean/Authentik-first: subscriber accounts + passwords live in
Cerulean's Authentik. Atlas checks entitlements server-to-server and never holds
Stripe keys.

## Stage 4 — Builder (Genie)

Atlas runs no builder, and there is nothing to bring up here for one. The
stack's builder is **Genie** ([genie.innotel.us](https://genie.innotel.us)), a
separate deployment that publishes into this forge over Gitea's API. The stage
Atlas owns is the *contract*: an account (or access token) Genie can use, Gitea
reachable from Genie's host on both HTTP and SSH, and — when subscriber access
is sold — the Magnate plan `atlas`.

```bash
# on Genie's host, once Atlas is up
curl -s -o /dev/null -w '%{http_code}\n' "$AGENT_ATLAS_URL/api/v1/version"
curl -s -u "$AGENT_ATLAS_USER:$AGENT_ATLAS_PASSWORD" "$AGENT_ATLAS_URL/api/v1/user"
```

See [genie.md](genie.md) for the full env contract, how to mint the token, and
what each check's answer means.

> **The Chef profile is retired** (convergence §2/§8). `make chef-up` no longer
exists; `chef-provisioner/` and [chef-auth-fork.md](chef-auth-fork.md) remain as
the record of that work.

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
  `GITEA_HTTP_PORT`/`GITEA_SSH_PORT`/`CONVEX_*` in `.env` and
  re-provision the NPM forwards — no code changes.
- **Secrets:** `.env` is derived from Cerulean Vault (`vault://` references,
  resolved by `setup.sh` / `make vault-sync`); rotate provider keys in the
  OmniRoute dashboard, never in code. `make vault-bootstrap` seeds this stack's
  generated secrets — it unions, so a re-run never rotates a credential a
  running service is using.
- **Billing (optional):** set `MAGNATE_URL` + `ENTITLEMENTS_API_TOKEN` (matching
  Magnate's `ENTITLEMENTS_API_TOKEN`) to gate paid developer seats. Magnate is
  Cerulean/Authentik-first — subscriber accounts live in Cerulean's Authentik.
- **Distro export:** Distro (BuilderOps) can push built projects to this Atlas
  instance's Gitea remotes. The remote SSH host is `git.<zone>` and the base URL
  is `GITEA_ROOT_URL`; configure those in Distro's `.env` (`ATLAS_URL` +
  `ATLAS_GIT_REMOTE`).
- **Unified vs split:** this compose runs standalone on its own server or as
  part of an all-encompassing stack — only `.env` (forward addresses/ports)
  and edge provisioning differ (see the platform stack README).
