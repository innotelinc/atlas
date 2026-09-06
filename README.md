<div align="center">

# 🗺️ Atlas — Build What's Next.

**Your coding & development platform — self-hosted, AI-powered, one gateway for every model.**

Atlas is the Innotel ecosystem's **CodeOps** home: a git forge and
development hub (Gitea) paired with an **AI app builder (Chef)** that
generates full-stack applications onto a **self-hosted Convex backend** —
with every model call routed through one **OmniRoute** gateway. Describe an
app, review the code in your own forge, and ship it — identity, secrets,
DNS, and billing from the Innotel Platform Stack behind you.

[![CI](https://github.com/innotelinc/atlas/actions/workflows/ci.yml/badge.svg)](https://github.com/innotelinc/atlas/actions/workflows/ci.yml)
[![License: AGPL-3.0-or-later](https://img.shields.io/badge/license-AGPL--3.0-or-later-brightgreen.svg)](LICENSE)

</div>

> **About Atlas** — source control, code review, CI/CD, and AI-assisted app
> generation for the whole platform: **Gitea** hosts every repository,
> **Chef** builds apps on **self-hosted Convex**, and **OmniRoute** is the
> single model provider behind Chef's codegen. **Landing page:**
> [innotelinc.github.io/atlas](https://innotelinc.github.io/atlas)

---

## Why Atlas

| Problem | Atlas answer |
| --- | --- |
| Repos scattered across SaaS forges | Self-hosted **Gitea** — repos, PRs, issues, wiki, packages, Actions CI |
| App scaffolding is manual | **Chef** turns a prompt into a full-stack app with realtime DB, auth, files, and workflows |
| App runtimes you don't control | **Self-hosted Convex** — generated apps run on your own backend |
| AI model lock-in | Every model call routes through **OmniRoute** — one gateway, many providers |
| Identity you don't control | Authentik-native SSO through Cerulean — one login for the whole stack |

## What it is

- **Repo & development hosting (Gitea)** — every Innotel platform repo keeps
  its source here: branches, pull requests, code review, issues and boards,
  wikis, releases, the package registry, and Gitea Actions CI/CD.
- **AI app builder (Chef)** — the Convex-team app builder "that knows
  backend": describe an app and Chef generates the database schema, auth,
  file uploads, realtime UIs, and background workflows on Convex.
- **App runtime backend (Convex, self-hosted)** — the open-source reactive
  database and compute engine generated apps run on, with a dashboard and
  CLI admin (`make convex-key`).
- **One model gateway (OmniRoute)** — Chef's codegen routes through
  OmniRoute's OpenAI-compatible endpoint, so provider accounts live in one
  gateway dashboard instead of Atlas code.
- **The whole Innotel stack behind it** — Authentik (identity), Infisical
  (secrets), Cerulean (DNS + TLS), Magnate (revenue), NPM Edge.

## 🚀 Quick start

```bash
git clone https://github.com/innotelinc/atlas.git
cd atlas
./setup.sh        # guard hooks, generated .env, clones upstream Chef
```

### 1. Core — Gitea + Convex

```bash
make up           # gitea, gitea-db, convex backend, convex dashboard
make convex-key   # generate the admin key for the Convex dashboard/CLI
```

### 2. Model gateway — OmniRoute

```bash
make gateway-check   # http://127.0.0.1:20128 — connect provider accounts
```

### 3. AI app builder — Chef

```bash
make chef-up      # build + start Chef from services/chef (upstream clone)
```

Full bring-up order, Authentik/Cerulean edge wiring, and the Chef auth fork
are in [docs/Deployment.md](docs/Deployment.md) and
[docs/Integrations.md](docs/Integrations.md).

## Technology stack

| Layer | Technology |
| --- | --- |
| Repo & dev hosting | Gitea (repos · PRs · issues · wiki · packages · Actions) |
| AI app builder | Chef (get-convex/chef — bolt.diy fork by the Convex team) |
| App runtime backend | Convex (self-hosted backend + dashboard) |
| Model gateway | OmniRoute (OpenAI-compatible gateway, single provider pool) |
| Identity | Authentik (OIDC / OAuth2 via Cerulean) |
| Secrets | Infisical (SecretOps — `.env` is derived) |
| Trust / DNS / TLS | Cerulean (TrustOps) |
| Revenue | Magnate (RevenueOps — paid developer seats) |
| Deployment | Docker Compose + NGINX Proxy Manager |

## 📚 Documentation

| Document | Purpose |
| --- | --- |
| [docs/stack.md](docs/stack.md) | Atlas's role in the Innotel Platform Stack (CodeOps) |
| [docs/Architecture.md](docs/Architecture.md) | System design, components, data flows |
| [docs/Integrations.md](docs/Integrations.md) | Gitea, Chef, Convex self-hosted, OmniRoute, Authentik |
| [docs/Deployment.md](docs/Deployment.md) | Bring-up runbook, Cerulean DNS/TLS, production notes |

## Repository layout

```
atlas/
├── docs/                      # Architecture, Integrations, Deployment, stack role
├── web/landing/               # Static GitHub Pages landing page
├── .github/workflows/         # CI, attribution guard, Pages publish
├── .githooks/                 # Local attribution guard (shared with CI)
├── docker-compose.yml         # Gitea + Convex core; gateway/chef profiles
├── services/                  # Upstream checkouts (Chef) — gitignored, via setup.sh
├── scripts/                   # setup.sh, commit-message policy
├── .env.example               # Environment template (never commit .env)
└── Makefile                   # Operator workflow
```

## Development & operations

```bash
make help        # every target, one view
make setup       # hooks + .env + preflight + Chef clone
make gateway-check  # OmniRoute model gateway
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

## 🏛️ Platform stack

Atlas is the ecosystem's **CodeOps** platform — source control, CI/CD, and
AI-assisted app building in the
[**Innotel Platform Stack**](https://github.com/innotelinc/innotel-platform-stack) —
the canonical single-responsibility architecture where Authentik owns identity,
Infisical owns secrets, Cerulean owns trust, ONYX owns storage, Magnate owns
revenue, and every other platform is a business function that consumes them.
See [docs/stack.md](docs/stack.md) for this platform's owns/consumes boundaries.
