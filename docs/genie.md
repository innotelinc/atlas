# Atlas — Genie (the builder)

**Genie** ([genie.innotel.us](https://genie.innotel.us)) is the ecosystem's one
builder: an agent workspace — the console and the `genie` CLI — that writes a
project in a sandbox, previews it running, and **publishes** it into a forge.

That forge is Atlas. Publishing creates (or reuses) the repository through
Gitea's API, commits, pushes once with the credential inline, and leaves
`origin` pointing at it, so the work carries on in the same directory. Atlas's
job is the account, the port, and the reachability; it runs no builder of its
own.

This page is the Atlas side of that contract. Genie's own docs
(`ontrak-genie/docs/operations.md` § *Atlas — the ecosystem's forge*) are the
other half and stay authoritative for Genie's behaviour.

## What Genie keeps in its `.env`

Atlas reads none of these — they are set on **Genie's** deployment.

| Variable | Example | Meaning |
| --- | --- | --- |
| `AGENT_ATLAS_URL` | `http://192.168.1.90:3004` or `https://git.innotel.us` | The address **Gitea** is published on. API calls, clone URL and push URL all follow this one value, so a wrong port fails at the first request |
| `AGENT_ATLAS_SSH_HOST` | `192.168.1.90` | The same machine, for working in a *folder* over SSH instead of cloning a repository |
| `AGENT_ATLAS_USER` | `admin` | A Gitea account |
| `AGENT_ATLAS_PASSWORD` | *(secret)* | That account's password **or an access token** — a token is what a deployment should hold. May be a `vault://` reference |
| `MAGNATE_ATLAS_PLAN` | `atlas` (default) | The plan that entitles a caller who has no deployment credential of their own |

`AGENT_ATLAS_URL` is **not** always port 3000. Atlas publishes Gitea on whatever
`GITEA_HTTP_PORT` in `deploy/.env` says (`docker ps` names the published port);
on the live host that is `3004`, and the same Gitea answers on the edge names
`https://git.innotel.us` and `https://atlas.innotel.us`.

## Two routes in, two gates

| Route | Credential | Gate |
| --- | --- | --- |
| **System** | `AGENT_ATLAS_USER` / `AGENT_ATLAS_PASSWORD` — the deployment's own | none: an operator's own forge is not a subscription |
| **Subscriber** | typed into the console, held for the session | `MAGNATE_ATLAS_PLAN`, when Magnate is configured and there is an identity to key on |

Gitea itself verifies the credential — `GET /api/v1/user` is the gate — and the
login it answers with is what Genie remembers, not the one that was typed. For
the subscriber route the plan is asked *first*, so a refusal reads as an add-on
with somewhere to subscribe; an unreachable Magnate is not a refusal, it falls
back to whether the deployment holds its own credential.

## Minting the credential

The deployment should hold an access token, not the admin password. On the Atlas
host:

```bash
docker exec -u git atlas-gitea gitea admin user generate-access-token \
  --username admin --token-name genie-system --scopes all --raw
```

Put the printed value in Genie's `AGENT_ATLAS_PASSWORD` (or in Cerulean Vault and
reference it there). Gitea accepts a token in the password position of Basic
auth, so nothing else changes. Revoke it at
`https://git.innotel.us/user/settings/applications`.

## Verifying, from Genie's host

```bash
curl -s -o /dev/null -w '%{http_code}\n' "$AGENT_ATLAS_URL/api/v1/version"   # 200, 401/403, or a refusal
curl -s -u "$AGENT_ATLAS_USER:$AGENT_ATLAS_PASSWORD" "$AGENT_ATLAS_URL/api/v1/user"
```

The second answers with the login it authenticated as — `401` means the
credential is wrong, and note that Gitea's own admin account is not necessarily
the host's root password. `403` from an anonymous `/api/v1/version` is Gitea
refusing the API to a caller without a token, not a broken API.

A publish also needs the **clone URL the API hands back** to resolve from
Genie's host, because Gitea builds it from `GITEA_ROOT_URL`:

```bash
curl -s -o /dev/null -w '%{http_code}\n' https://git.innotel.us/api/v1/version
```

If that fails while the `:3004` address works, the edge name is not resolving
from Genie's network — point `AGENT_ATLAS_URL` at the working address rather than
changing `GITEA_ROOT_URL`.

## Atlas-side checklist

1. `make up` and `make ps` — `gitea`, `gitea-db`, `convex`,
   `convex-dashboard` healthy.
2. Gitea reachable from Genie's host on **both** HTTP (`GITEA_HTTP_PORT`) and
   SSH (`GITEA_SSH_PORT`, only needed for folder mounts).
3. An account and access token exist for the deployment
   (`gitea admin user list`), and the token can create repositories.
4. If subscriber access is sold: `MAGNATE_URL` + `ENTITLEMENTS_API_TOKEN` set on
   Genie's side, and an `atlas` plan in Magnate's catalog.
5. The apps Genie publishes keep their source here; an app whose data target is
   Convex deploys onto the backend this stack runs.

## Known-good wiring (2026-10-18)

On the `ontrak` deployment, against this stack:

- `AGENT_ATLAS_URL=http://192.168.1.90:3004`, `AGENT_ATLAS_SSH_HOST=192.168.1.90`,
  `AGENT_ATLAS_USER=admin`
- `GET /api/v1/user` with the deployment credential → `200`, answered as `admin`
  (the same request through the edge, `https://git.innotel.us/api/v1/user`, also
  `200`)
- `GET /api/v1/user/repos` → `200`; `POST /api/v1/user/repos` → `201` and
  `DELETE` of that probe repository → `204` (the probe was removed; nothing is
  left behind)
- Gitea SSH accepted a connection on `192.168.1.90:2222`
- anonymous `/api/v1/version` answers `403` — Gitea refusing the API to a caller
  without a credential, not a broken API
