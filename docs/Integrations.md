# Atlas — Integrations

Atlas glues **Gitea** (repo hosting) and **Convex (self-hosted)** (app backend)
into one CodeOps platform, with **OmniRoute** supplying the models, and rides the
Innotel platform services (Authentik, Cerulean Vault, Cerulean, Magnate, NPM
Edge) for identity, secrets, trust, revenue, and edge.

**Chef is retired.** The bolt.diy-fork AI builder used to sit on top of this as
Atlas's generation surface; in the convergence (Phase 3) the builder surface is
**Studio** (Olympus), and a Studio plan targets either a container or the Convex
backend Atlas runs. `chef-provisioner/` and
[`docs/chef-auth-fork.md`](chef-auth-fork.md) are kept as the record — nothing
builds or runs Chef.

Upstreams:

| Component | Upstream | License |
| --- | --- | --- |
| Gitea | https://github.com/go-gitea/gitea | MIT |
| Convex backend (self-hosted) | https://github.com/get-convex/convex-backend | Apache-2.0 |
| OmniRoute | https://github.com/diegosouzapw/OmniRoute | — |

> Chef (`get-convex/chef`, Apache-2.0) was a fourth upstream until Phase 3. It is
> no longer built, run, or pinned; its notice and the auth-fork notes stay in the
> repo as the retirement record.

## Gitea — repo & development hosting

- Image `gitea/gitea` with Postgres storage (`gitea-db`), data on named
  volumes. First boot creates the admin from `ATLAS_ADMIN_USER` /
  `ATLAS_ADMIN_EMAIL` via the install UI or `gitea admin` commands.
- **Authentik SSO.** In Cerulean's Authentik create an OAuth2 provider +
  application (`atlas-gitea`), then register it with Gitea:

  ```bash
  docker compose exec gitea gitea admin auth add-oauth \
    --name authentik --provider openidConnect \
    --key "$OIDC_CLIENT_ID" --secret "$OIDC_CLIENT_SECRET" \
    --auto-discover-url "$OIDC_ISSUER_URL/.well-known/openid-configuration"
  ```

  Gitea maps the `email`/`name` claims; keep `DISABLE_REGISTRATION=true` so
  accounts come only from Authentik or the admin.
- **Actions CI.** Gitea ships Actions; add an `act_runner` (image
  `gitea/act_runner`) registered to the instance to execute pipeline jobs.
  Packages publish to Gitea's built-in registry.

## Convex — self-hosted reactive backend

- Images `ghcr.io/get-convex/convex-backend` (backend, `:3210` + http-actions
  site `:3211`) and `ghcr.io/get-convex/convex-dashboard` (`:6791`), per the
  upstream [self-hosted guide](https://github.com/get-convex/convex-backend/blob/main/self-hosted/README.md).
- SQLite on a named volume by default; production can move the store to
  Postgres/MySQL (`POSTGRES_URL` / `MYSQL_URL`) and file state to S3-compatible
  storage (`S3_ENDPOINT_URL` + the `S3_STORAGE_*_BUCKET` vars) — env pass-throughs
  documented in the upstream compose.
- Admin keys come from inside the container:

  ```bash
  make convex-key            # docker compose exec convex ./generate_admin_key.sh
  ```

  Then point the CLI at Atlas Convex instead of the cloud:

  ```bash
  npm install convex@latest
  # .env.local in the project:
  #   CONVEX_SELF_HOSTED_URL='http://127.0.0.1:3210'
  #   CONVEX_SELF_HOSTED_ADMIN_KEY='<admin key>'
  npx convex dev
  ```

- The dashboard reaches the backend at
  `NEXT_PUBLIC_DEPLOYMENT_URL=http://127.0.0.1:3210` (localhost publishes).
  When generated apps go public, publish `convex` to the edge and set
  `CONVEX_CLOUD_ORIGIN`/`NEXT_PUBLIC_DEPLOYMENT_URL` to the HTTPS host.

## Chef — retired builder (record only)

Chef (a bolt.diy fork by the Convex team) was the "AI app builder that knows
backend": it generated full-stack apps whose database, auth, files, realtime,
and workflows ran on Convex. **It was retired in Phase 3 of the convergence.**
Nothing in this repo builds, runs, or pins it any more: the `chef` service, the
`chef-provisioner` image wiring, the `chef-sites` volume and the compose profile
are gone from `docker-compose.yml`, `setup.sh` no longer clones an upstream
checkout, and CI no longer syntax-checks one. The builder surface is **Studio**
(Olympus), pointed at the Distro control plane and able to target this Convex.

What stays, deliberately: `docs/chef-auth-fork.md` (the auth-fork scope and
workstreams, as the record of how it was built) and `chef-provisioner/`. The
text below is the historical wiring, kept only so the record reads end-to-end.

<details><summary>Historical Chef wiring (pre-Phase 3)</summary>

Three wiring layers, in bring-up order:

1. **Backend functions → Atlas Convex.** Chef's own backend code lives in its
   `convex/` directory. Deploy it to Atlas Convex and set its env:

   ```bash
   cd services/chef
   npm install -g pnpm && pnpm i
   npx convex dev --once          # uses CONVEX_SELF_HOSTED_URL + admin key
   npx convex env set BIG_BRAIN_HOST "$BIG_BRAIN_HOST"
   npx convex env set CONVEX_OPENAI_API_KEY "$OMNIROUTE_API_KEY"
   ```

2. **Model providers → OmniRoute.** Chef reads provider keys from env
   (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GOOGLE_API_KEY`, `XAI_API_KEY` in
   `app/lib/.server/llm/provider.ts`, plus `OPENAI_API_KEY` in
   `convex/openaiProxy.ts` and `convex/summarize.ts`). Each SDK factory
   (`createOpenAI`, `createAnthropic`, …) accepts a `baseURL`; because
   OmniRoute is OpenAI-compatible, the single clean override is
   `createOpenAI({ baseURL: CHEF_OMNIROUTE_BASE_URL, apiKey: … })` for the
   OpenAI case and an OpenAI-compatible shim for the others. This patch is
   intentionally small and documented in the fork commit.

   **Landed** (in the gitignored `services/chef` checkout): the OpenAI case
   reads `baseURL: getEnv('CHEF_OMNIROUTE_BASE_URL') || undefined`, so an
   unset value is upstream behavior and a set one routes every OpenAI-model
   turn through the gateway. `CHEF_OMNIROUTE_BASE_URL` / `_API_KEY` are wired
   into the `chef` service and `.env.example`. Two things the patch does not
   do, both deliberate: the Anthropic/Google/XAI cases still build their own
   SDK clients against the vendor (an OpenAI-compatible shim for each is the
   next step, and until then a `claude-*`/`gemini-*` choice reaches the
   vendor directly), and Chef's build-time dependency check
   (`depscheck.mjs`) still refuses to start with **no** provider key at all —
   see `docs/chef-auth-fork.md` for why `.env.example` keeps exactly one
   placeholder and marks it as such.

3. **Auth fork → Authentik.** Upstream Chef authenticates through Convex's
   hosted control plane (OAuth against `api.convex.dev` — also the default of
   `BIG_BRAIN_HOST`/`VITE_PROVISION_HOST`). Upstream's own guidance says a
   production fork must replace that with its own OAuth. Atlas replaces it
   with Cerulean's Authentik: register an OAuth2 provider (`atlas-chef`,
   redirect `https://chef.<zone>/api/auth/callback`), swap Chef's login flow
   for an Authorization Code Grant against Authentik, and clear
   `VITE_PROVISION_HOST`/`BIG_BRAIN_HOST` so no traffic leaves the box. The
   fork is **landed and serving in production mode**: `make chef-up` builds
   the fork image (`pnpm build` + `remix-serve` on `:4310`, workstream 3b.3)
   and the login round-trip works end-to-end against Authentik. Clearing the
   hosted-plane envs is gated on provisioning localization (3b.2) so that
   project creation still functions; until then the defaults stay.
   Full scope, workstreams, and the open design questions (project model on
   self-hosted Convex, deploy tokens, git push path) live in
   [docs/chef-auth-fork.md](chef-auth-fork.md).

</details>

## OmniRoute — the shared model provider

- **Shared gateway on Zeus (Group 2 of the mesh, `10.10.2.1:20128`).**
  Atlas runs no OmniRoute of its own; connect provider accounts once in
  the Zeus OmniRoute dashboard.
- Consumers point at
  `OMNIROUTE_BASE_URL=http://10.10.2.1:20128/v1` with
  `OMNIROUTE_API_KEY`, so Atlas never stores vendor keys — one pool, many
  providers, single point of rotation. Requires the WireGuard mesh to be
  up (see `ips`).

## Authentik — identity (IdentityOps)

- Cerulean hosts the shared Authentik; every Atlas login goes through it
  (`auth.cerulean.innotel.us`, aliased `auth.atlas.innotel.us`).
- Registered application: `atlas-gitea` (Gitea OAuth2). Groups: `atlas-admins`
  gates admin. The `atlas-chef` application was **deleted from Authentik** along
  with Chef's retirement (Phase 3), so no orphan provider remains.

## Cerulean Vault · Cerulean · Magnate · NPM Edge

- **Cerulean Vault (SecretOps):** Atlas `.env` derives from Vault. Database
  passwords, the Convex instance secret and the OAuth session secret are
  `vault://cerulean/atlas#<KEY>` references in `.env.example`; `setup.sh` runs
  `scripts/vault-bootstrap.py` (which seeds the keys Atlas generates) and then
  `scripts/vault-resolve.py --write`, because Atlas is compose-and-images only
  and nothing in a running container can resolve a reference. A reference that
  does not resolve stops the setup — never an empty credential. The
  Authentik-issued client secrets are stored from what Authentik printed, with
  `scripts/vault-migrate.py`; it is also the migration path off Infisical, the
  legacy store (`docs/stack.md` § Secrets). `.env` and `services/` never enter
  git.
- **Cerulean (TrustOps):** DNS records + per-zone wildcard TLS for
  `git.innotel.us`, `chef.innotel.us`, `convex.innotel.us`; CNAMEs to the
  apex, DNS-01 issuance via the shared BIND TSIG key.
- **Magnate (RevenueOps):** optional paid developer seats — Authentik group
  membership (`paid_users`) grants Atlas access; cancellation deactivates it.
- **NPM Edge:** proxy hosts for each public Atlas host, forwarding to
  `127.0.0.1` ports of this stack (see `scripts/npm-proxy-hosts.py` pattern
  in sibling platforms / docs/Deployment.md).

## Studio ↔ Distro ↔ Atlas (Builder ↔ Tenancy ↔ CodeOps)

**Studio (Olympus)** is the builder: it generates a project from a plan and
packages it. **Distro** is the tenancy service — accounts, per-user gateway
keys, quota and audit for that builder. **Atlas** is CodeOps: Gitea repos plus a
self-hosted Convex backend. The shared workflow:

1. Describe an app in Studio; the plan carries a **target**
   (`lib/targets.ts`) — `container` by default, or `convex` when it should run
   on the Convex backend Atlas hosts.
2. Studio asks Distro's control plane for a per-user gateway key, quota and an
   audit record (`CONTROL_PLANE_INTERNAL_URL` + `CONTROL_INTERNAL_TOKEN`).
3. The packaged project goes to an Atlas/Gitea remote and Gitea Actions builds
   and ships it.

> The bolt.diy front door that used to live in Distro (`apps/web`, an in-browser
> WebContainer builder) was **retired** in Phase 3 — Studio is the one web UI, and
> Distro keeps only the control plane. Distro's bundled gateway went with it: the
> platform runs **one** OmniRoute, on Zeus, over the mesh.

Both consume the same Magnate instance for billing (RevenueOps) and the same
Cerulean Authentik for identity / DNS / TLS (TrustOps). Atlas runs no OmniRoute
of its own; Studio and the other consumers reach the shared Zeus gateway over
the WireGuard mesh.
