# Atlas — Architecture

Atlas is the platform's **CodeOps** home: a git forge (Gitea) plus an
AI-assisted application builder (Chef) whose generated apps run on a
self-hosted Convex backend, with every model call behind one OmniRoute
gateway. It ships as one Compose project (`name: atlas`) that runs on a
single host or spreads across hosts behind the shared edge.

## Components

```
                     ┌─────────────────────────────────────────────┐
        users ──────►│                   EDGE (NPM)                │
                     │   git.<zone> · chef.<zone> · convex.<zone>  │
                     └──────┬──────────────┬──────────────┬────────┘
                            │              │              │
                            ▼              ▼              ▼
                    ┌──────────────┐ ┌──────────────┐ ┌──────────────┐
                    │    GITEA     │ │    CHEF      │ │  CONVEX      │
                    │  CodeOps     │ │  AI builder  │ │  backend     │
                    │  repos · PRs │ │  (web)       │ │  reactive    │
                    │  issues · CI │ │   │          │ │  DB + funcs  │
                    │  packages    │ │   ▼          │ └──────┬───────┘
                    └──────────────┘ │  CONVEX CLI  │        │
                            │        └──────┬───────┘        │
                            ▼               ▼                ▼
                   ┌──────────────┐  ┌──────────────┐  ┌──────────────┐
                   │  GITEA DB    │  │  OMNIROUTE   │  │ CONVEX DASH  │
                   │  postgres    │  │ model gateway│  │   admin UI   │
                   └──────────────┘  └──────────────┘  └──────────────┘
```

| Service | Image / source | Ports (host) | Notes |
| --- | --- | --- | --- |
| `gitea` | `gitea/gitea:1.27.x` | `3000` (web), `22` (ssh) | env-configurable |
| `gitea-db` | `postgres:16-alpine` | — | Gitea's store |
| `convex` | `ghcr.io/get-convex/convex-backend` | `3210`, `3211` (127.0.0.1) | SQLite on a volume by default |
| `convex-dashboard` | `ghcr.io/get-convex/convex-dashboard` | `6791` (127.0.0.1) | points at `convex` |
| `omniroute` (profile) | `diegosouzapw/omniroute` | `20128` (127.0.0.1) | OpenAI-compatible `/v1` |
| `chef` (profile) | build from `services/chef` | `5173` (127.0.0.1) | upstream get-convex/chef |

## Data flows

### Source control (Gitea)

- Developers authenticate through Cerulean's Authentik (OIDC); first login
  auto-provisions the matching Gitea account from the identity provider.
- Repos push over SSH (`git.<zone>:22`) or HTTPS. Actions runners execute
  CI/CD jobs defined in each repo; packages publish to Gitea's registry.
- Atlas is the canonical remote for every Innotel platform repo.

### App building (Chef → Convex)

1. A developer describes an app in the Chef web UI.
2. Chef's agent loop calls its model providers — all routed through the
   OmniRoute gateway (`OMNIROUTE_BASE_URL`) — to generate code.
3. Generated code is deployed to the **self-hosted Convex backend**
   (`convex`, `:3210`) using the admin key from `make convex-key`.
4. The finished source is pushed to Gitea, where Actions CI takes over.

### Model gateway (OmniRoute)

- One endpoint (`http://10.10.2.1:20128/v1` — the shared OmniRoute on
  Zeus, Group 2 of the mesh), one credential pool. Chef's provider keys
  point at OmniRoute instead of vendor endpoints, so provider accounts
  rotate in the gateway dashboard — never in Atlas code.

## Configuration

All knobs live in `.env` (derived from `.env.example`; never committed).
Domain, ports, versions, database credentials, and provider keys are all
env-driven. Production secrets are pulled from Infisical at setup.

## Identity & trust boundaries

- **Login:** everything goes through Cerulean's Authentik. Gitea registers
  an OAuth2 application; Chef's upstream auth is replaced by an Authentik
  OAuth provider in the self-hosted fork (see
  [Integrations.md](Integrations.md) — *Auth fork*).
- **Network:** internal ports (Convex, dashboard, OmniRoute, Chef) publish
  to `127.0.0.1` only; the edge fronts the canonical public hosts with
  Cerulean-issued per-zone wildcard TLS.
- **Ports:** `GITEA_HTTP_PORT` / `GITEA_SSH_PORT` / `CONVEX_*` /
  `OMNIROUTE_PORT` / `CHEF_PORT` are overridable so Atlas coexists with
  other platforms on a unified host.
