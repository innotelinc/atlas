# Atlas — Integrations

Atlas glues four open-source systems — Gitea, Chef, Convex (self-hosted),
and OmniRoute — into one CodeOps platform and rides the Innotel platform
services (Authentik, Infisical, Cerulean, Magnate, NPM Edge) for identity,
secrets, trust, revenue, and edge.

Upstreams:

| Component | Upstream | License |
| --- | --- | --- |
| Gitea | https://github.com/go-gitea/gitea | MIT |
| Chef | https://github.com/get-convex/chef | Apache-2.0 |
| Convex backend (self-hosted) | https://github.com/get-convex/convex-backend | Apache-2.0 |
| OmniRoute | https://github.com/diegosouzapw/OmniRoute | — |

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

## Chef — AI app builder (on Atlas Convex)

Chef (a bolt.diy fork by the Convex team) is the "AI app builder that knows
backend": it generates full-stack apps whose database, auth, files, realtime,
and workflows run on Convex. Atlas builds it from source (cloned by
`setup.sh` into `services/chef`, gitignored) and points it at the Atlas
Convex backend.

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
   `createOpenAI({ baseURL: OMNIROUTE_BASE_URL, apiKey: OMNIROUTE_API_KEY })`
   for the OpenAI case and an OpenAI-compatible shim for the others. This
   patch is intentionally small and documented in the fork commit.

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

## OmniRoute — the provider for Chef

- **Shared gateway on Zeus (Group 2 of the mesh, `10.10.2.1:20128`).**
  Atlas runs no OmniRoute of its own; connect provider accounts once in
  the Zeus OmniRoute dashboard.
- Chef's codegen agent points at
  `OMNIROUTE_BASE_URL=http://10.10.2.1:20128/v1` with
  `OMNIROUTE_API_KEY`, so Atlas never stores vendor keys — one pool, many
  providers, single point of rotation. Requires the WireGuard mesh to be
  up (see innotel-platform-stack).

## Authentik — identity (IdentityOps)

- Cerulean hosts the shared Authentik; every Atlas login goes through it
  (`auth.cerulean.innotel.us`, aliased `auth.atlas.innotel.us`).
- Registered applications: `atlas-gitea` (Gitea OAuth2) and `atlas-chef`
  (Chef OAuth, after the auth fork). Groups: `atlas-admins` gates admin in
  both.

## Infisical · Cerulean · Magnate · NPM Edge

- **Infisical (SecretOps):** Atlas `.env` is derived — `setup.sh` pulls
  credentials from the `atlas` project, and generated secrets are written
  back; `.env` and `services/` never enter git.
- **Cerulean (TrustOps):** DNS records + per-zone wildcard TLS for
  `git.innotel.us`, `chef.innotel.us`, `convex.innotel.us`; CNAMEs to the
  apex, DNS-01 issuance via the shared BIND TSIG key.
- **Magnate (RevenueOps):** optional paid developer seats — Authentik group
  membership (`paid_users`) grants Atlas access; cancellation deactivates it.
- **NPM Edge:** proxy hosts for each public Atlas host, forwarding to
  `127.0.0.1` ports of this stack (see `scripts/npm-proxy-hosts.py` pattern
  in sibling platforms / docs/Deployment.md).

## Distro ↔ Atlas (BuilderOps ↔ CodeOps)

Distro builds apps live in the browser; Atlas is the stack's CodeOps home
(Gitea repos + Chef AI app builder on self-hosted Convex). The shared workflow:

1. Describe an app in Distro → AI writes code in-browser (WebContainer).
2. Export to Git → Distro pushes the project to an Atlas/Gitea remote
   (`ATLAS_URL` + `ATLAS_GIT_REMOTE` in Distro's `.env`).
3. Atlas receives the source; Chef can scaffold a Convex backend for it.
4. Gitea + Gitea Actions CI/CD build and ship it.

Both platforms consume the same Magnate instance for billing (RevenueOps) and
the same Cerulean Authentik for identity / DNS / TLS (TrustOps). Atlas does not
run its own OmniRoute gateway — Chef reaches the shared Zeus gateway over the
WireGuard mesh; Distro runs its own gateway in its compose stack but points at
the same upstream provider pool.
