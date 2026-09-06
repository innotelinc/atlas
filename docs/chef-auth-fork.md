# Chef Authentik Auth Fork — Scope & Design

**Status: baselined — foundation landed, fork code pending** · September 2026

Upstream is cloned at `services/chef` (gitignored) and **pinned to
`d8a6cb6`** (`Add 'us' to new anthropic models (#980)`). The repo-side
foundation (stage 3a env plumbing) is in `docker-compose.yml` /
`.env.example`; the fork code itself lives in the `services/chef` checkout
(stages 3b–3c below).

Chef (the AI app builder) is the last Atlas surface that still talks to the
outside world for identity: upstream Chef authenticates through Convex's
**hosted control plane** (OAuth against `api.convex.dev`), which is also the
default of its `VITE_PROVISION_HOST` / `BIG_BRAIN_HOST` envs. The stack's
golden rules say identity belongs to Authentik and nothing may leave the box
for a core function — so Chef's login and project provisioning must be
replaced by an **Authorization Code Grant against Cerulean's Authentik**
with the provisioning endpoints served by the Atlas self-hosted Convex
backend. This document scopes that fork.

Reference points:

- `docs/Integrations.md` — Chef bring-up and wiring layers (Convex backend,
  OmniRoute, auth fork).
- `docs/Deployment.md` — Stage 4 (Chef) operating modes.
- Innotel platform stack README — the registered OIDC client table reserves
  **`atlas-chef`** with redirect `chef.<zone>/api/auth/callback` for exactly
  this fork.
- Upstream: [get-convex/chef](https://github.com/get-convex/chef) (a
  bolt.diy fork), cloned by `setup.sh` into `services/chef` (gitignored).

---

## 1. Today's wiring (hosted control plane)

| Concern | Current | Files (in `services/chef`) |
| --- | --- | --- |
| Login | **WorkOS-backed Convex auth**: OAuth app created under a Convex dashboard team, team selector, then cloud `provision_and_authorize` — see upstream issue #911 | `convex/auth.config.ts`, `app/components/chat/ChefAuthWrapper.tsx`, `app/routes/api.convex.callback.ts`, `convex/sessions.ts` |
| Project provisioning | Hosted control-plane API (create project, tokens) | `VITE_PROVISION_HOST` (`https://api.convex.dev`) |
| Account/big-brain endpoints | Hosted | `BIG_BRAIN_HOST` (`https://api.convex.dev`) |
| Chef's own backend | Deployed to **Atlas** self-hosted Convex (`convex/` functions, `make convex-key` admin key) | `npx convex dev --once` against `CONVEX_SELF_HOSTED_URL` |
| Model providers | OmniRoute OpenAI-compatible gateway (`OMNIROUTE_BASE_URL` / `OMNIROUTE_API_KEY`) | `app/lib/.server/llm/provider.ts`, `convex/openaiProxy.ts`, `convex/summarize.ts` |
| Runtime | `make chef-up` runs **local-dev mode** (`pnpm run dev` on `:5173`, upstream README default) until the fork lands | Dockerfile (profile `chef`) |

So today the app's *codegen* is self-hosted (Atlas Convex + OmniRoute), but
its *login and provisioning* still depend on Convex's cloud. The fork closes
that gap.

## 1b. File map (upstream `d8a6cb6`) — what the fork touches

| File | Role today | Fork change |
| --- | --- | --- |
| `app/routes/api.convex.callback.ts` | Cloud `provision_and_authorize` after WorkOS login | Replace with Authentik OIDC callback → local provisioning |
| `convex/auth.config.ts` + `app/components/chat/ChefAuthWrapper.tsx` | Convex/WorkOS auth providers | Authentik provider (OIDC code grant), `CHEF_OIDC_*` envs |
| `convex/sessions.ts` | Session + team/`profile` via `BIG_BRAIN_HOST/api/dashboard/profile` | Local user/session from the Authentik subject; drop cloud profile |
| `convex/convexProjects.ts` | `BIG_BRAIN_HOST/api/create_project` + `dashboard/authorize` (deploy keys) | Local project rows + per-app deploy keys on Atlas Convex |
| `convex/messages.ts` | Team projects list + `delete_project` via big-brain | Local project store |
| `convex/deploy.ts`, `app/lib/.server/deploy-simple.ts` | Deploy generated apps to the provisioned (cloud) deployment | Deploy to the per-app Atlas Convex backend (`CONVEX_SELF_HOSTED_URL` + key) |
| `app/lib/convexProvisionHost.ts`, `convexProfile.ts`, `convexUsage.ts`, `convexOptins.ts`, `app/routes/api.enhance-prompt.ts` | `VITE_PROVISION_HOST`/`PROVISION_HOST` → `api.convex.dev` (profile, usage, opt-ins) | Local equivalents or no-op until apps deploy |

`PROVISION_HOST` (server env) and `VITE_PROVISION_HOST`/`BIG_BRAIN_HOST`
(client/server envs) are the two seams; clearing them must not break the
build, only the login/provisioning that the fork replaces.

## 2. Target architecture

```
Learner/operator
   │  browser
   ▼
chef.<zone>  (Chef app, served from the Atlas chef container)
   │  /api/auth/callback  ← OIDC redirect_uri (client: atlas-chef)
   ▼
Cerulean Authentik  (auth.cerulean.innotel.us — IdentityOps)
   │  id_token: subject = Authentik user (openid profile email groups)
   ▼
Chef session (httpOnly cookie, HMAC-signed — same pattern as the Zeus
   portal lib/auth.ts; SESSION_SECRET from Infisical)
   │
   ├─ Chef backend functions → Atlas Convex (self-hosted, local)
   │     account + project + deployment-token provisioning now live here
   │     (replacing the hosted VITE_PROVISION_HOST / BIG_BRAIN_HOST calls)
   └─ model calls → OmniRoute (unchanged)
```

Non-negotiable outcomes:

- **No outbound identity/provisioning traffic**: `VITE_PROVISION_HOST` and
  `BIG_BRAIN_HOST` are cleared/removed; nothing in the container calls
  `api.convex.dev`.
- **Authentik is the only IdP**: no Chef password store, no second login.
  Disable the user in Cerulean and Chef access dies.
- **Single login for the stack**: same Authentik session users already have
  from every other platform.

## 3. Workstreams

### 3a. OIDC client + env passthrough (this repo, no fork code)

1. In Cerulean's Authentik, register the OAuth2/OIDC provider +
   application **`atlas-chef`** (redirect
   `https://chef.<zone>/api/auth/callback`, scopes
   `openid profile email groups`) and issue client id/secret into Infisical.
2. Add the env plumbing the container will need (today the `chef` compose
   service passes only `VITE_*` model/convex vars):
   - `CHEF_OIDC_ISSUER_URL`, `CHEF_OIDC_CLIENT_ID=atlas-chef`,
     `CHEF_OIDC_CLIENT_SECRET` (prefixed so they never collide with Gitea's
     `OIDC_*` client `atlas-gitea`)
   - `CHEF_SESSION_SECRET` (HMAC cookie key)
   - `IDP_ADMIN_GROUP=atlas-admins`
   - keep `VITE_CONVEX_URL`, `CONVEX_SELF_HOSTED_URL` /
     `CONVEX_SELF_HOSTED_ADMIN_KEY`; drop `VITE_PROVISION_HOST` /
     `BIG_BRAIN_HOST` from the shipped defaults once the fork is the mode.
   **Done** — see `docker-compose.yml` and `.env.example` (all defaults
   empty/unchanged).

### 3b. Auth fork (in `services/chef`, the upstream checkout)

1. **Replace the login flow** with an OIDC authorization-code + PKCE grant
   against `OIDC_ISSUER_URL` (discovery via
   `/.well-known/openid-configuration`), exchanging the code server-side and
   storing the Authentik `sub` as the user identity. `/api/auth/callback`
   is the registered redirect. Map `email`/`name` claims onto the Chef user
   model; promote users in `IDP_ADMIN_GROUP` (`atlas-admins`) to Chef admin.
2. **Localize provisioning**: the account/project endpoints Chef previously
   proxied to the hosted plane become Convex functions deployed to Atlas
   Convex (project rows, per-project deploy tokens/keys, workspace state).
   This is the fork's main surface — see Open Questions Q1/Q2 before coding.
3. **Serve a production build**: switch `chef-up` from the upstream dev
   server to `pnpm build` + serve (or the upstream Dockerfile) so the
   container is a real service, not a dev-mode process.
4. **Keep the OmniRoute override** (3b is additive; the provider shim in
   §1 does not change).
5. Patch is carried in the fork commit(s); document the file list in this
   repo (mirroring how `patches/` works in the zeus repo) so upstream
   upgrades are re-baselined, not re-invented.

### 3c. Verification

- **Egress check**: run the chef container with `strace`/`tcpdump`-level
  egress logging or a proxy and prove no request to `api.convex.dev` (or any
  non-Cerulean/OmniRoute host) leaves the box during login + a codegen run.
- **Login**: operator signs in at `chef.<zone>` → redirected to
  `auth.cerulean.innotel.us` → back; disabled user is refused; admin from
  `atlas-admins` sees the admin surface.
- **Codegen**: a generated app deploys to Atlas Convex (its own project
  key scope) and its source lands as a Gitea repo (`git.innotel.us`).
- **CI**: a unit test asserting the container env contains no
  `VITE_PROVISION_HOST`/`BIG_BRAIN_HOST`/`api.convex.dev` values.

## 4. Sequencing

| Step | Where | Done when |
| --- | --- | --- |
| A — OIDC client + env passthrough | this repo | env vars present; provider registered; container passes them |
| B — login swap (OIDC code grant + session) | `services/chef` | login round-trips through Authentik; cookie session works |
| C — provisioning localization | `services/chef` convex/ | project creation/deploy tokens served by Atlas Convex |
| D — production serve + docs | this repo + fork | `make chef-up` serves a build; Deployment/Integrations updated; hosted defaults removed |

Steps B–D are the actual fork work and live in the `services/chef` checkout
(a gitignored upstream clone) — they are intentionally **not** in this
repo's tree until the fork is baselined upstream.

## 5. Open design questions — recommended resolutions (owner confirm)

1. **Project model on self-hosted Convex.** Chef provisions *projects* via
   the cloud control plane; a self-hosted `convex-backend` instance is **one
   deployment** (pushing two apps to the same instance overwrites).
   **Recommendation: deployment-per-app (option a)** — the fork's
   provisioning service starts one Atlas Convex backend (container, SQLite
   volume, own admin key) per generated app, mirroring cloud semantics and
   isolation. For dev/LAN, one shared instance is fine while only one app
   is live.
2. **Deploy tokens.** With deployment-per-app, each app's backend gets its
   own admin key generated at provisioning time (replaces cloud
   `dashboard/authorize`). Single shared instance (dev): the operator
   `make convex-key` key until scoped per-project keys exist.
3. **Git push target.** **Recommendation: a Gitea machine token from
   Infisical**, used by the provisioning service to create repos per app
   via the Gitea API (idempotent by repo name). Keep the operator's
   Authentik identity out of Chef's push path.
4. **Fallback switch.** Keep `VITE_PROVISION_HOST`/`BIG_BRAIN_HOST`
   **empty by default** with a documented dev-only escape hatch (the
   `STRIPE_*` pattern). The stage-3c egress check must still pass with them
   empty — it fails if the running container ever calls `api.convex.dev`.
