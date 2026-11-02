/**
 * The warehouse phone, as the measurements open screens on it.
 *
 * A mid Android on weak signal: Chromium with the CPU slowed 4x and the
 * network held to slow 4G (1.6 Mbit/s, 150 ms round trip — the profile
 * Lighthouse calls "Slow 4G"), a 360x800 touch viewport, a cold cache. The
 * phone budget gate (`measure-phone-budget.mjs`) and the warehouse-scale
 * measurement (`measure-scale-screens.mjs`) open their screens on the same
 * phone, so their numbers can be read against each other.
 *
 * `serve` serves `dist/` itself — gzip, a fallback to index.html, `/api`
 * proxied to the stack — because `vite preview` sends scripts uncompressed
 * and the slow network would then measure a download three times the real one.
 */
import { createReadStream, existsSync, statSync } from "node:fs";
import { createServer, request as httpRequest } from "node:http";
import { availableParallelism, loadavg } from "node:os";
import { extname, join } from "node:path";
import { createGzip } from "node:zlib";

export const CPU_SLOWDOWN = 4;
export const SLOW_4G = {
  offline: false,
  latency: 150,
  downloadThroughput: (1.6 * 1024 * 1024) / 8,
  uploadThroughput: (750 * 1024) / 8,
};

/** The browser context options of the phone. */
export const PHONE_CONTEXT = {
  viewport: { width: 360, height: 800 },
  deviceScaleFactor: 2,
  isMobile: true,
  hasTouch: true,
  locale: "en-US",
};

const TYPES = {
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript",
  ".css": "text/css",
  ".json": "application/json",
  ".svg": "image/svg+xml",
  ".png": "image/png",
  ".ico": "image/x-icon",
  ".woff2": "font/woff2",
  ".woff": "font/woff",
};
const COMPRESSIBLE = new Set([".html", ".js", ".css", ".json", ".svg"]);

const isFile = (path) => existsSync(path) && statSync(path).isFile();

/** Serve `dist` on a free local port, `/api` and `/uploads` proxied to `api`. */
export function serve(dist, api) {
  const upstreamUrl = new URL(api);
  const server = createServer((req, res) => {
    const url = new URL(req.url, "http://x");
    if (url.pathname.startsWith("/api") || url.pathname.startsWith("/uploads")) {
      const upstream = httpRequest(
        {
          host: upstreamUrl.hostname,
          port: upstreamUrl.port,
          method: req.method,
          path: req.url,
          headers: { ...req.headers, host: upstreamUrl.host },
        },
        (answer) => {
          res.writeHead(answer.statusCode ?? 502, answer.headers);
          answer.pipe(res);
        },
      );
      upstream.on("error", () => res.writeHead(502).end());
      req.pipe(upstream);
      return;
    }
    let file = join(dist, decodeURIComponent(url.pathname));
    if (!file.startsWith(dist) || !isFile(file)) {
      // Only a path with no extension is a route; a missing asset stays a 404.
      if (extname(url.pathname)) return void res.writeHead(404).end();
      file = join(dist, "index.html");
    }
    const ext = extname(file);
    const headers = { "content-type": TYPES[ext] ?? "application/octet-stream" };
    if (COMPRESSIBLE.has(ext) && /gzip/.test(req.headers["accept-encoding"] ?? "")) {
      res.writeHead(200, { ...headers, "content-encoding": "gzip" });
      createReadStream(file).pipe(createGzip()).pipe(res);
    } else {
      res.writeHead(200, headers);
      createReadStream(file).pipe(res);
    }
  });
  return new Promise((ok) => server.listen(0, "127.0.0.1", () => ok(server)));
}

/**
 * Sign in and return the refresh cookie for `origin`, plus the access token.
 *
 * A freshly reset database has not finished onboarding, and every route then
 * redirects to the workflow wizard; this posts the warehouse setup
 * (equipment_wms). 409 means it was done already, which is the state to leave
 * alone.
 */
export async function login({ api, origin, email, password }) {
  const response = await fetch(`${api}/api/v1/auth/login`, {
    method: "POST",
    headers: { "content-type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({ username: email, password }),
  });
  if (!response.ok) {
    throw new Error(`login failed: ${response.status} ${await response.text()}`);
  }
  const { access_token: token } = await response.clone().json();
  const setup = await fetch(`${api}/api/v1/onboarding/setup`, {
    method: "POST",
    headers: { "content-type": "application/json", authorization: `Bearer ${token}` },
    body: JSON.stringify({ profile_id: "equipment_wms" }),
  });
  if (!setup.ok && setup.status !== 409) {
    throw new Error(`onboarding failed: ${setup.status} ${await setup.text()}`);
  }
  const cookie = response.headers
    .getSetCookie()
    .map((c) => c.match(/^refresh_token=([^;]+)/))
    .find(Boolean);
  if (!cookie) throw new Error("login set no refresh_token cookie");
  return {
    token,
    cookie: { name: "refresh_token", value: cookie[1], url: origin, httpOnly: true, sameSite: "Lax" },
  };
}

/** Put `page` on the phone: no cache, slow 4G, the CPU slowed. */
export async function throttle(context, page) {
  const cdp = await context.newCDPSession(page);
  await cdp.send("Network.enable");
  await cdp.send("Network.setCacheDisabled", { cacheDisabled: true });
  await cdp.send("Network.emulateNetworkConditions", SLOW_4G);
  await cdp.send("Emulation.setCPUThrottlingRate", { rate: CPU_SLOWDOWN });
  return cdp;
}

/**
 * What the scripts `page` loads weigh on the wire, gzip: start it before the
 * navigation and call what it returns once the network is idle. A size the
 * browser can no longer give — the page closed first — counts nothing, and is
 * handled the moment it is asked for: left for the sum, a refusal ended the
 * run as an unhandled rejection instead of reporting the screen.
 */
export function scriptBytes(page) {
  const sizes = [];
  page.on("requestfinished", (request) => {
    if (request.resourceType() === "script") {
      sizes.push(request.sizes().then((s) => s.responseBodySize, () => 0));
    }
  });
  return async () => (await Promise.all(sizes)).reduce((a, b) => a + b, 0);
}

export const median = (values) => [...values].sort((a, b) => a - b)[Math.floor(values.length / 2)];

/**
 * How busy the host is while it measures: the one-minute load average against
 * the cores. A host with as much runnable work as cores (the fleet runs suites
 * side by side) stretches every wall-clock figure, and a timing read there
 * says as much about the queue for the CPU as about the screen.
 */
export function hostLoad([load] = loadavg(), cores = availableParallelism()) {
  return { load, cores, loaded: load >= cores };
}
