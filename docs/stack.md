# Atlas in the Innotel Platform Stack

**Role: CodeOps** — the coding & development platform.

Atlas owns everything about *building software* for the ecosystem: source
control, code review, CI/CD, package hosting, and the AI app builder that
generates full-stack applications onto a self-hosted realtime backend.

## Boundaries

- **Owns:** repositories, forks, pull requests, code review, issues/boards,
  wikis, releases, package registry, Actions CI/CD, AI-assisted application
  generation (Chef), and the self-hosted Convex backend generated apps run on.
- **Consumes:** Authentik (identity — every Atlas login goes through
  Cerulean's Authentik), Infisical (secrets), Cerulean (DNS + TLS + NPM edge
  hosts), Magnate (billing/entitlements for paid dev seats), NPM Edge.
- **Does not own:** identity, secrets, certificates/DNS, billing, storage
  (ONYX), or any production runtime of the platforms it helps build. Apps
  built in Atlas deploy to their owning platform; Atlas holds the source.
- **Consumes (shared stack services):** Authentik (identity — via Cerulean),
  Infisical (secrets), Cerulean (DNS + TLS + NPM edge hosts),
  Magnate (billing/entitlements for paid dev seats — RevenueOps), NPM Edge.
  Distro (BuilderOps) exports built apps to Atlas/Gitea and the two share the
  same OmniRoute gateway pool, Magnate billing and Cerulean Authentik SSO.

## Why it exists

Every platform in the portfolio needs somewhere to keep its code, review
changes, and run CI. Rather than each platform embedding a git forge, Atlas
is the single CodeOps home — the same way Authentik is the single identity
home. Its AI builder (Chef) makes the stack self-extending: describe an app,
Chef scaffolds it on the self-hosted Convex backend, and the resulting source
lands in Atlas's Gitea.

## Service map (Atlas-owned)

| Component | Technology | Job |
| --- | --- | --- |
| Repo & dev hosting | Gitea | Repos, PRs, issues, wiki, packages, Actions CI |
| AI app builder | Chef (get-convex/chef) | Prompt-to-app generation on Convex |
| App runtime backend | Convex (self-hosted) | Reactive DB + compute for built apps |
| Model gateway | OmniRoute | One OpenAI-compatible endpoint for Chef's models |

## In the ecosystem

| Flow | Path |
| --- | --- |
| Identity | Cerulean's Authentik (`auth.cerulean.innotel.us`) → OIDC → Gitea/Chef sessions |
| Secrets | Atlas `.env` derives from Infisical (SecretOps); never committed |
| Trust | Cerulean issues DNS + per-zone wildcard TLS; NPM Edge fronts `git.<zone>` etc. |
| Revenue | Magnate plans/entitlements gate paid developer seats |
| Source of truth | This repository's sibling docs: `README.md`, `docs/Architecture.md`, `docs/Integrations.md`, `docs/Deployment.md` |

Back to the canonical definition: the
[Innotel Platform Stack](https://github.com/innotelinc/innotel-platform-stack).
