# Atlas in the Innotel Platform Stack

**Role: CodeOps** — the coding & development platform.

Atlas owns everything about *building software* for the ecosystem: source
control, code review, CI/CD, package hosting, and the AI app builder that
generates full-stack applications onto a self-hosted realtime backend.

> **Convergence:** see the [**build-plane convergence plan**](https://github.com/innotelinc/innotel-platform-stack/blob/main/docs/convergence-onyx-olympus-distro-atlas.md)
> — the shared target for ONYX, Atlas, Distro and Olympus. Atlas's part: keep
> CodeOps (Gitea, Convex, CI, the canonical git remote), **retire Chef as a
> builder** (§2/§8 — applied: the `chef` profile, its provisioner and the
> `chef-up`/`chef-down` targets are gone, and Convex stays as a deploy target),
> and move secrets to Cerulean Vault (§6 — applied).

## Boundaries

- **Owns:** repositories, forks, pull requests, code review, issues/boards,
  wikis, releases, package registry, Actions CI/CD, and the self-hosted Convex
  backend apps deploy onto.
- **Does not own building.** One platform, one builder, and it is Olympus's
  engine (convergence §2). Atlas used to run Chef for this; it no longer does.
- **Does not own:** identity, secrets, certificates/DNS, billing, storage
  (ONYX), or any production runtime of the platforms it helps build. Apps
  built in Atlas deploy to their owning platform; Atlas holds the source.
- **Consumes (shared stack services):** Authentik (identity — every Atlas
  login goes through Cerulean's Authentik, via OIDC), Cerulean Vault (secrets),
  Cerulean (DNS + TLS + NPM edge hosts), Magnate (billing/entitlements for
  paid dev seats — RevenueOps), NPM Edge.
  Distro (BuilderOps) exports built apps to Atlas/Gitea and the two share the
  same OmniRoute gateway pool, Magnate billing and Cerulean Authentik SSO.

## Why it exists

Every platform in the portfolio needs somewhere to keep its code, review
changes, and run CI. Rather than each platform embedding a git forge, Atlas
is the single CodeOps home — the same way Authentik is the single identity
home. The stack's builder lives in Olympus (describe an app, get a running
container), the source it produces lands in Atlas's Gitea, and the apps that
want a realtime backend deploy onto the self-hosted Convex that Atlas runs.

## Service map (Atlas-owned)

| Component | Technology | Job |
| --- | --- | --- |
| Repo & dev hosting | Gitea | Repos, PRs, issues, wiki, packages, Actions CI |
| App runtime backend | Convex (self-hosted) | Reactive DB + compute — a deploy target for built apps |
| Model gateway | OmniRoute | One OpenAI-compatible endpoint for the stack's models |
| ~~AI app builder~~ | ~~Chef (get-convex/chef)~~ | **Retired as a builder** (§2/§8). Convex stays; the record is `chef-provisioner/` + [chef-auth-fork.md](chef-auth-fork.md) |

## In the ecosystem

| Flow | Path |
| --- | --- |
| Identity | Cerulean's Authentik (`auth.cerulean.innotel.us`) → OIDC → Gitea sessions |
| Secrets | Atlas `.env` derives from Cerulean Vault (SecretOps) — `vault://` references resolved by `setup.sh`, never committed |
| Trust | Cerulean issues DNS + per-zone wildcard TLS; NPM Edge fronts `git.<zone>` etc. |
| Revenue | Magnate plans/entitlements gate paid developer seats |
| Source of truth | This repository's sibling docs: `README.md`, `docs/Architecture.md`, `docs/Integrations.md`, `docs/Deployment.md` |

## Secrets (Cerulean Vault)

Atlas is **compose-and-images only**, so it cannot resolve a `vault://`
reference at runtime the way ONYX's Go services or Distro's Node services do.
The resolution point is setup:

| Step | Where | What |
| --- | --- | --- |
| Seed | `make vault-bootstrap` (`scripts/vault-bootstrap.py`) | Writes `cerulean/atlas` — **unions**, so a key already in Vault is never rotated by a re-run. Generates `GITEA_DB_PASSWORD` and `CONVEX_INSTANCE_SECRET`; never invents an Authentik-issued secret |
| Resolve | `setup.sh`, `make vault-sync` (`scripts/vault-resolve.py --write`) | Reads each `vault://` reference in `.env` and replaces it with the value, since Compose cannot |
| Verify | `make vault-check` (`scripts/vault-resolve.py --check`) | Proves every reference resolves; writes nothing |
| Migrate | `scripts/vault-migrate.py` | The Infisical → Vault path (legacy store; Atlas runs no Infisical service) |

`OIDC_CLIENT_SECRET` is **issued by Cerulean Authentik**, so it is stored from
what Authentik printed rather than generated:

```bash
python3 scripts/vault-migrate.py --from-env-file .env --keys OIDC_CLIENT_SECRET
```

A reference that cannot be resolved is a hard failure in `setup.sh`: a stack
that starts with an empty credential fails later as an authentication error
that names the wrong service. Without `VAULT_ADDR`, setup generates local values
for the three keys Atlas owns and says so, so a dev box still comes up.

The path-scoped policy is `atlas` over `cerulean/atlas*` — never the
platform-wide `cerulean` policy or the root token. The token is delivered as
`data/vault/token/atlas.token` and read through `VAULT_TOKEN_FILE`.

Back to the canonical definition: the
[Innotel Platform Stack](https://github.com/innotelinc/innotel-platform-stack).
