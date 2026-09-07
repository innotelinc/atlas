#!/usr/bin/env node
/**
 * Atlas Chef provisioner — deployment-per-app Convex backends.
 *
 * Serves Chef's local provisioning API (fork workstream 3b.2): each generated
 * app gets its OWN `convex-backend` container (named `chef-proj-<slug>` on
 * the Atlas compose network, SQLite data on a per-project volume) with its
 * own instance secret and admin key — mirroring the cloud control plane's
 * "one project = one deployment" semantics instead of sharing Chef's own
 * backend instance.
 *
 * Runs in the `chef-provisioner` compose service (profile `chef`) with the
 * host Docker socket mounted; it shells out to the `docker` CLI (bundled in
 * the image) so no docker SDK dependency is needed.
 *
 * API (JSON, all endpoints require `Authorization: Bearer <CHEF_PROVISION_TOKEN>`):
 *   GET    /health                              -> { ok: true }
 *   POST   /projects      { name, slug }        -> provision + start + admin key
 *   GET    /projects                            -> list with status
 *   GET    /projects/<slug>                     -> status + deployment info
 *   DELETE /projects/<slug>                     -> stop, remove container + volume
 *
 * Deployment info returned by POST/GET:
 *   {
 *     name: "chef-proj-<slug>",                 // container name / INSTANCE_NAME
 *     slug,
 *     deploymentUrl: "http://chef-proj-<slug>:3210",  // reachable on the compose network
 *     deploymentName: "chef-proj-<slug>",
 *     adminKey: "<generated admin key>",        // only on POST + admin-key requests
 *     status: "running" | "exited" | ...,
 *   }
 */

import http from "node:http";
import { execFile } from "node:child_process";
import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";

const PORT = parseInt(process.env.PORT || "9080", 10);
const TOKEN = process.env.CHEF_PROVISION_TOKEN || "";
const NETWORK = process.env.CHEF_DOCKER_NETWORK || "atlas_default";
const IMAGE =
  process.env.CHEF_CONVEX_IMAGE ||
  `ghcr.io/get-convex/convex-backend:${process.env.CHEF_CONVEX_VERSION || "latest"}`;
const DATA_VOLUME_PREFIX = process.env.CHEF_DATA_VOLUME_PREFIX || "chef-proj-data";

// Static site hosting (generated apps): the compose service mounts this
// directory on the host and an nginx container serves it. Files are written
// here from the per-project Docker volumes (read via a helper container).
const SITES_DIR = process.env.CHEF_SITES_DIR || "/srv/sites";
const MAX_SITE_ZIP_BYTES = 512 * 1024 * 1024;

// Slugs whose containers were removed but whose static files are still
// deployed. Compose re-applies the current label set on `up`, so the nginx
// label block is regenerated on every boot to stay in sync.
const DELETED_FILE = path.join(SITES_DIR, ".deleted-slugs");
const SITES_HOST_HEADER = process.env.CHEF_SITES_HOST || "chef-sites:8080";

function loadDeletedSlugs() {
  try {
    return new Set(fs.readFileSync(DELETED_FILE, "utf8").split("\n").map((l) => l.trim()).filter(Boolean));
  } catch {
    return new Set();
  }
}

function saveDeletedSlugs(set) {
  fs.mkdirSync(SITES_DIR, { recursive: true });
  fs.writeFileSync(DELETED_FILE, [...set].join("\n") + "\n");
}

function deletedSetLine(slugs) {
  return `"-e", "CHEF_DELETED_SLUGS=${[...slugs].join(",")}"`;
}

function slugify(name) {
  const slug = String(name || "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 40);
  if (!slug) throw Object.assign(new Error("invalid project name"), { status: 400 });
  return slug;
}

function containerName(slug) {
  return `chef-proj-${slug}`;
}

// ─── docker CLI helpers ─────────────────────────────────────────────────────

function docker(args, opts = {}) {
  return new Promise((resolve, reject) => {
    execFile("docker", args, { maxBuffer: 4 * 1024 * 1024, ...opts }, (err, stdout, stderr) => {
      if (err) {
        err.dockerStderr = String(stderr || "").trim();
        reject(err);
      } else {
        resolve(String(stdout || ""));
      }
    });
  });
}

async function dockerJson(args) {
  const out = await docker(args);
  try {
    return JSON.parse(out);
  } catch {
    return {};
  }
}

function randomSecret(bytes = 32) {
  return crypto.randomBytes(bytes).toString("hex");
}

// ─── provisioning ───────────────────────────────────────────────────────────

async function waitHealthy(name, timeoutMs = 90000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      // /version returns a plain-text body — success is exit code 0, not JSON.
      await docker(["exec", name, "curl", "-sf", "--max-time", "3", "http://localhost:3210/version"]);
      return true;
    } catch {
      // not ready yet
    }
    await new Promise((r) => setTimeout(r, 2000));
  }
  return false;
}

async function projectInfo(name) {
  const inspect = await dockerJson(["inspect", name]).catch(() => null);
  const status = inspect?.[0]?.State?.Status || "missing";
  const adminKey = status === "running"
    ? await docker(["exec", name, "./generate_admin_key.sh"]).catch(() => "")
    : "";
  return { status, adminKey: adminKey.trim() };
}

function writeJson(res, code, body) {
  const raw = JSON.stringify(body);
  res.writeHead(code, { "Content-Type": "application/json", "Content-Length": Buffer.byteLength(raw) });
  res.end(raw);
}

function authOk(req) {
  if (!TOKEN) return true; // token empty = open on the compose network (dev default)
  const header = req.headers.authorization || "";
  const m = /^Bearer\s+(.+)$/.exec(header);
  if (!m) return false;
  const a = Buffer.from(m[1]);
  const b = Buffer.from(TOKEN);
  return a.length === b.length && crypto.timingSafeEqual(a, b);
}

// Binary-safe body reader: returns a Buffer (callers decode to UTF-8 only
// for JSON bodies; site uploads are zip bytes and must survive untouched).
function readBody(req, limit = 1 << 20) {
  return new Promise((resolve, reject) => {
    let size = 0;
    const chunks = [];
    req.on("data", (c) => {
      size += c.length;
      if (size > limit) {
        reject(Object.assign(new Error("body too large"), { status: 413 }));
        req.destroy();
        return;
      }
      chunks.push(c);
    });
    req.on("end", () => resolve(Buffer.concat(chunks)));
    req.on("error", reject);
  });
}

const server = http.createServer(async (req, res) => {
  try {
    const url = new URL(req.url, "http://localhost");
    const p = url.pathname;

    // Liveness probe stays unauthenticated so container healthchecks work
    // without embedding the provision token.
    if (req.method === "GET" && p === "/health") {
      return writeJson(res, 200, { ok: true });
    }

    if (!authOk(req)) {
      return writeJson(res, 401, { error: "unauthorized" });
    }

    // POST /projects
    if (req.method === "POST" && p === "/projects") {
      let body;
      try {
        body = JSON.parse(((await readBody(req))?.toString("utf8")) || "{}");
      } catch {
        return writeJson(res, 400, { error: "invalid JSON body" });
      }
      let slug;
      try {
        slug = slugify(body.slug || body.name);
      } catch (e) {
        return writeJson(res, e.status || 400, { error: e.message });
      }
      const name = containerName(slug);
      const secret = randomSecret();
      const volume = `${DATA_VOLUME_PREFIX}-${slug}`;
      const origin = `http://${name}:3210`;

      try {
        const existing = await dockerJson(["inspect", name]).catch(() => null);
        if (existing?.[0]) {
          return writeJson(res, 409, { error: `project backend already exists: ${name}` });
        }
      } catch {
        // not present — proceed
      }

      try {
        await docker([
          "run", "-d",
          "--name", name,
          "--network", NETWORK,
          "--restart", "unless-stopped",
          "--label", `com.innotel.chef.project=${slug}`,
          "-e", `INSTANCE_NAME=${name}`,
          "-e", `INSTANCE_SECRET=${secret}`,
          "-e", `CONVEX_CLOUD_ORIGIN=${origin}`,
          "-e", `CONVEX_SITE_ORIGIN=http://${name}:3211`,
          "-e", "DO_NOT_REQUIRE_SSL=1",
          "-e", "DISABLE_BEACON=1",
          "-e", "RUST_LOG=info",
          "-v", `${volume}:/convex/data`,
          IMAGE,
        ]);
      } catch (e) {
        return writeJson(res, 500, { error: `failed to start ${name}: ${e.dockerStderr || e.message}` });
      }

      const healthy = await waitHealthy(name);
      if (!healthy) {
        return writeJson(res, 500, { error: `${name} did not become healthy in time` });
      }
      const { adminKey } = await projectInfo(name);
      if (!adminKey) {
        return writeJson(res, 500, { error: `${name} healthy but admin key could not be read` });
      }
      // The new project can now receive static deploys; drop any deleted-mark.
      const deleted = loadDeletedSlugs();
      if (deleted.delete(slug)) saveDeletedSlugs(deleted);

      return writeJson(res, 201, {
        name,
        slug,
        deploymentUrl: origin,
        deploymentName: name,
        siteUrl: `http://${SITES_HOST_HEADER}/sites/${slug}/`,
        adminKey,
        status: "running",
      });
    }

    // GET /projects | GET /projects/<slug> | DELETE /projects/<slug>
    const m = /^\/projects(?:\/([^/]+))?$/.exec(p);
    if (m && req.method === "GET" && !m[1]) {
      const out = await docker(["ps", "-a", "--filter", "label=com.innotel.chef.project", "--format", "{{.Names}}\t{{.Status}}"]);
      const projects = [];
      for (const line of out.trim().split("\n")) {
        if (!line.trim()) continue;
        const [name, status] = line.split("\t");
        projects.push({ name, slug: name.replace(/^chef-proj-/, ""), deploymentUrl: `http://${name}:3210`, status: status || "unknown" });
      }
      return writeJson(res, 200, { projects });
    }
    if (m && m[1]) {
      const slug = m[1];
      const name = containerName(slug);
      if (req.method === "GET") {
        const info = await projectInfo(name);
        if (info.status === "missing") return writeJson(res, 404, { error: `no backend for ${slug}` });
        return writeJson(res, 200, {
          name,
          slug,
          deploymentUrl: `http://${name}:3210`,
          deploymentName: name,
          status: info.status,
          adminKey: info.adminKey || undefined,
        });
      }
      if (req.method === "DELETE") {
        await docker(["rm", "-f", name]).catch(() => {});
        await docker(["volume", "rm", "-f", `${DATA_VOLUME_PREFIX}-${slug}`]).catch(() => {});
        // Keep deployed static files, but remember the deletion so the nginx
        // label block stops routing it even before the next `up` re-applies
        // labels. POST /projects un-marks when the slug is reused.
        const deleted = loadDeletedSlugs();
        deleted.add(slug);
        saveDeletedSlugs(deleted);
        return writeJson(res, 200, { ok: true, slug });
      }
    }

    // ─── static site deploys (generated apps) ──────────────────────────────
    const sm = /^\/sites\/([a-z0-9][a-z0-9-]*)(?:\/(.*))?$/.exec(p);
    if (sm) {
      const slug = sm[1];
      const name = containerName(slug);
      const siteRoot = path.join(SITES_DIR, slug);

      // PUT/POST: replace the site from a uploaded zip (or bare file).
      if (req.method === "PUT" || req.method === "POST") {
        const buffer = await readBody(req, MAX_SITE_ZIP_BYTES);
        if (!buffer.length) {
          return writeJson(res, 400, { error: "empty upload" });
        }
        const inspect = await dockerJson(["inspect", name]).catch(() => null);
        if (!inspect?.[0]) {
          return writeJson(res, 404, { error: `no backend for ${slug}` });
        }
        try {
          const tmpZip = `/tmp/chef-site-${slug}-${Date.now()}.zip`;
          fs.writeFileSync(tmpZip, buffer);
          const tmpOut = `/tmp/chef-site-${slug}-${Date.now()}`;
          fs.mkdirSync(tmpOut, { recursive: true });
          // unzip is present on the node:22-alpine provisioner image via busybox? No —
          // install unzip in the Dockerfile. Use `unzip -o` so redeploys overwrite.
          await new Promise((resolve, reject) => {
            execFile("unzip", ["-o", tmpZip, "-d", tmpOut], { maxBuffer: 8 * 1024 * 1024 }, (err) =>
              err ? reject(err) : resolve(),
            );
          });
          // Flatten a single top-level directory (zip made from `dist/`).
          const entries = fs.readdirSync(tmpOut);
          const srcDir = entries.length === 1 && fs.statSync(path.join(tmpOut, entries[0])).isDirectory()
            ? path.join(tmpOut, entries[0])
            : tmpOut;
          fs.rmSync(siteRoot, { recursive: true, force: true });
          fs.mkdirSync(path.dirname(siteRoot), { recursive: true });
          // /tmp and /srv/sites can be different filesystems — copy + drop,
          // don't rename.
          fs.cpSync(srcDir, siteRoot, { recursive: true });
          fs.rmSync(tmpZip, { force: true });
          fs.rmSync(tmpOut, { recursive: true, force: true });
          const files = countFiles(siteRoot);
          return writeJson(res, 201, {
            ok: true,
            slug,
            siteUrl: `http://${SITES_HOST_HEADER}/sites/${slug}/`,
            files,
          });
        } catch (e) {
          return writeJson(res, 500, { error: `site deploy failed: ${e.message}` });
        }
      }

      // DELETE: remove the deployed files for this slug.
      if (req.method === "DELETE") {
        fs.rmSync(siteRoot, { recursive: true, force: true });
        const deleted = loadDeletedSlugs();
        deleted.add(slug);
        saveDeletedSlugs(deleted);
        return writeJson(res, 200, { ok: true, slug });
      }

      // GET: deploy status.
      if (req.method === "GET") {
        if (!fs.existsSync(siteRoot)) {
          return writeJson(res, 404, { error: `no site deployed for ${slug}` });
        }
        return writeJson(res, 200, { slug, siteUrl: `http://${SITES_HOST_HEADER}/sites/${slug}/`, files: countFiles(siteRoot) });
      }
    }

    return writeJson(res, 404, { error: "not found" });
  } catch (err) {
    console.error("[chef-provisioner]", err);
    if (!res.headersSent) writeJson(res, 500, { error: err.message || "internal error" });
  }
});

function countFiles(dir) {
  let n = 0;
  const walk = (d) => {
    for (const entry of fs.readdirSync(d, { withFileTypes: true })) {
      if (entry.isDirectory()) walk(path.join(d, entry.name));
      else n++;
    }
  };
  try {
    walk(dir);
  } catch {
    /* removed concurrently */
  }
  return n;
}

server.listen(PORT, "0.0.0.0", () => {
  console.log(`[chef-provisioner] listening on :${PORT} (network ${NETWORK}, image ${IMAGE})`);
});
