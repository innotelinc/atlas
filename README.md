<div align="center">

# 🗺️ Atlas — Build What's Next.

**Your coding & development platform — self-hosted, AI-powered, one gateway for every model.**

Atlas is the Innotel ecosystem's **CodeOps** home: a git forge and
development hub (Gitea) with a **self-hosted Convex backend** for the apps
the ecosystem builds — every model call in the stack routed through one
**OmniRoute** gateway. Keep the source, review it, run CI, and host the
realtime backend those apps deploy onto — identity, secrets, DNS, and billing
from the Innotel Platform Stack behind you.

[![CI](https://github.com/innotelinc/atlas/actions/workflows/ci.yml/badge.svg)](https://github.com/innotelinc/atlas/actions/workflows/ci.yml)
[![Conformity](https://github.com/innotelinc/atlas/actions/workflows/conform.yml/badge.svg)](https://github.com/innotelinc/atlas/actions/workflows/conform.yml)
[![License: AGPL-3.0-or-later](https://img.shields.io/badge/license-AGPL--3.0--or--later-brightgreen.svg)](LICENSE)

</div>

> **About Atlas** — source control, code review, CI/CD, and the runtime
> backend for the whole platform: **Gitea** hosts every repository,
> **self-hosted Convex** is a deploy target for the apps Olympus's builder
> produces, and **OmniRoute** is the single model provider they share.
> **Landing page:** [innotelinc.github.io/atlas](https://innotelinc.github.io/atlas)

---

## Why Atlas

| Problem | Atlas answer |
| --- | --- |
| Repos scattered across SaaS forges | Self-hosted **Gitea** — repos, PRs, issues, wiki, packages, Actions CI |
| App scaffolding is manual | The ecosystem's builder (Olympus's Studio + factory) turns a prompt into a running app; Atlas keeps the source and CI for it |
| App runtimes you don't control | **Self-hosted Convex** — realtime apps deploy onto your own backend |
| AI model lock-in | Every model call routes through **OmniRoute** — one gateway, many providers |
| Identity you don't control | Authentik-native SSO through Cerulean — one login for the whole stack |

## What it is

- **Repo & development hosting (Gitea)** — every Innotel platform repo keeps
  its source here: branches, pull requests, code review, issues and boards,
  wikis, releases, the package registry, and Gitea Actions CI/CD.
- **App runtime backend (Convex, self-hosted)** — the open-source reactive
  database and compute engine apps deploy onto, with a dashboard and CLI admin
  (`make convex-key`). It is a deploy target the building platform may pick, not
  a builder of its own.
- **One model gateway (OmniRoute)** — the platform's single OpenAI-compatible
  endpoint, so provider accounts live in one gateway dashboard instead of in
  Atlas code.
- **The whole Innotel stack behind it** — Authentik (identity), Cerulean Vault
  (secrets), Cerulean (DNS + TLS), Magnate (revenue), NPM Edge.

> **Chef is retired as a builder.** Atlas used to run the Convex team's Chef
> (`get-convex/chef`) as an opt-in `chef` profile. The build-plane convergence
> plan settled on one builder for the whole stack — Olympus's engine, because it
> is the only one of the three that ends with a running, named application — so
> the profile is gone from `docker-compose.yml`, the `chef-up`/`chef-down`
> targets are gone, and Atlas runs no builder. Convex stays: it is a genuine
> deploy target. `chef-provisioner/` and [docs/chef-auth-fork.md](docs/chef-auth-fork.md)
> remain as the record of that work.

## 🚀 Quick start

```bash
git clone https://github.com/innotelinc/atlas.git
cd atlas
./setup.sh        # guard hooks, secrets resolved into .env, preflight
```

### 1. Core — Gitea + Convex

```bash
make up           # gitea, gitea-db, convex backend, convex dashboard
make convex-key   # generate the admin key for the Convex dashboard/CLI
```

### 2. Model gateway — OmniRoute

```bash
make gateway-check   # verify the shared OmniRoute on Zeus (Group 2) is reachable
```

### 3. Building apps — elsewhere

Atlas runs no builder. The stack's one builder is Olympus's engine (Studio →
the factory → `package-app`/`package-website` → a running container); the apps
it produces keep their source **here** and may deploy onto Convex, which this
stack hosts.

Full bring-up order and the Authentik/Cerulean edge wiring are in
[docs/Deployment.md](docs/Deployment.md) and
[docs/Integrations.md](docs/Integrations.md).

## Technology stack

| Layer | Technology |
| --- | --- |
| Repo & dev hosting | Gitea (repos · PRs · issues · wiki · packages · Actions) |
| App runtime backend | Convex (self-hosted backend + dashboard) — a deploy target for built apps |
| Model gateway | OmniRoute (OpenAI-compatible gateway, single provider pool) |
| Identity | Authentik (OIDC / OAuth2 via Cerulean) |
| Secrets | Cerulean Vault (SecretOps — `vault://` refs, `.env` is derived) |
| Trust / DNS / TLS | Cerulean (TrustOps) |
| Revenue | Magnate (RevenueOps — paid developer seats) |
| Deployment | Docker Compose + NGINX Proxy Manager |

## 📚 Documentation

| Document | Purpose |
| --- | --- |
| [docs/stack.md](docs/stack.md) | Atlas's role in the Innotel Platform Stack (CodeOps) |
| [docs/Architecture.md](docs/Architecture.md) | System design, components, data flows |
| [docs/Integrations.md](docs/Integrations.md) | Gitea, Convex self-hosted, OmniRoute, Authentik, the shared builder |
| [docs/Deployment.md](docs/Deployment.md) | Bring-up runbook, Cerulean DNS/TLS, production notes |
| [docs/chef-auth-fork.md](docs/chef-auth-fork.md) | **Historical** — the design record for the retired Chef Authentik auth fork |

## Repository layout

```
atlas/
├── docs/                      # Architecture, Integrations, Deployment, stack role
├── web/landing/               # Static GitHub Pages landing page
├── .github/workflows/         # CI, attribution guard, Pages publish
├── .githooks/                 # Local attribution guard (shared with CI)
├── docker-compose.yml         # Gitea + Convex core (the chef profile is retired)
├── chef-provisioner/          # RETIRED — the record of Chef's per-app provisioning
├── services/                  # Upstream checkouts — gitignored; unused since Chef retired
├── scripts/                   # setup.sh, commit-message policy
├── .env.example               # Environment template (never commit .env)
└── Makefile                   # Operator workflow
```

## Development & operations

```bash
make help        # every target, one view
make setup       # hooks + .env (secrets resolved) + preflight
make gateway-check  # verify the shared OmniRoute gateway (Zeus Group 2)
make check-commits
```

## Hosted landing page

The project landing page is published through GitHub Pages at
[https://innotelinc.github.io/atlas/](https://innotelinc.github.io/atlas/),
maintained in [web/landing/index.html](web/landing/index.html) and deployed by
[.github/workflows/pages.yml](.github/workflows/pages.yml).

## Community & contribution

- Report issues: https://github.com/innotelinc/atlas/issues
- Contributing: [CONTRIBUTING.md](CONTRIBUTING.md)

---

*Atlas — Build What's Next. © 2026*

## License

Atlas is licensed under the GNU Affero General Public License v3.0 or later
(AGPL-3.0-or-later). See [LICENSE](LICENSE) for the full text.

Atlas bundles four open-source components with their licenses retained in-tree:

| Component | Upstream | License |
|---|---|---|
| Gitea | https://github.com/go-gitea/gitea | MIT |
| Chef | https://github.com/get-convex/chef | Apache-2.0 |
| Convex backend (self-hosted) | https://github.com/get-convex/convex-backend | Apache-2.0 |
| OmniRoute | https://github.com/diegosouzapw/OmniRoute | — (vendor snapshot) |

## 🏛️ Platform stack

Atlas is the ecosystem's **CodeOps** platform — source control, CI/CD, and
AI-assisted app building in the
[**Innotel Platform Stack**](https://github.com/innotelinc/innotel-platform-stack) —
the canonical single-responsibility architecture where Authentik owns identity,
Cerulean Vault owns secrets, Cerulean owns trust, ONYX owns storage, Magnate owns
revenue, and every other platform is a business function that consumes them.
See [docs/stack.md](docs/stack.md) for this platform's owns/consumes boundaries.
