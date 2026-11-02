#!/usr/bin/env node
/**
 * What each screen downloads, and when it becomes usable, on a warehouse phone.
 *
 * The warehouse-scale measurement (`load_tests/scale/measure.py`) seeds an
 * organization of hundreds of thousands of products and asks how every screen
 * a warehouse uses daily behaves at that size. This is its browser half: it
 * opens each screen cold on the phone of the phone budget (`phone-profile.mjs`:
 * CPU 4x, slow 4G, 360x800) and records, per screen,
 *
 *   usableMs — from the navigation until the heading is on the page, the
 *              network has gone quiet (nothing in flight, nothing new for
 *              `QUIET_MS` — scripts as well as API requests, because a screen
 *              whose code is still downloading has not asked for its data
 *              yet) and no loading indicator is left on it: the moment the
 *              data is there to act on. The median of `SCALE_RUNS` runs.
 *   api      — every API request the screen sent: method, path, status, the
 *              bytes of its answer and how long it took over the phone's
 *              network. A screen that fetches the whole catalogue shows here
 *              as one answer the size of the catalogue.
 *
 * The screens come from a JSON file the Python half writes (a name and a path
 * each, the ids in the path chosen from the seeded organization), and the
 * result goes to another:
 *
 *   npm run build
 *   SCALE_API=http://127.0.0.1:8000 SCALE_SCREENS=screens.json \
 *     SCALE_OUT=browser.json node scripts/measure-scale-screens.mjs
 */
import { existsSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "@playwright/test";
import { login, median, PHONE_CONTEXT, serve, throttle } from "./phone-profile.mjs";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const dist = join(root, "dist");

const API = process.env.SCALE_API ?? "http://127.0.0.1:8000";
const EMAIL = process.env.DEV_ADMIN_EMAIL ?? "admin@example.com";
const PASSWORD = process.env.DEV_ADMIN_PASSWORD ?? "Admin123";
const RUNS = Number(process.env.SCALE_RUNS ?? 3);
const SCREENS_FILE = process.env.SCALE_SCREENS;
const OUT = process.env.SCALE_OUT;
/** How long the API has to stay quiet before the screen counts as settled. */
const QUIET_MS = 1500;
/** What the screens show while they wait: spinners, skeletons, busy regions. */
const LOADERS = '.animate-spin, .animate-pulse, [aria-busy="true"]';
const TIMEOUT_MS = 120_000;

if (!SCREENS_FILE || !OUT) {
  console.error("measure-scale-screens: set SCALE_SCREENS (input) and SCALE_OUT (output).");
  process.exit(2);
}
if (!existsSync(join(dist, "index.html"))) {
  console.error("measure-scale-screens: dist/index.html not found — run `npm run build` first.");
  process.exit(2);
}

const screens = JSON.parse(readFileSync(SCREENS_FILE, "utf8"));

async function measureOnce(context, origin, screen) {
  const page = await context.newPage();
  await throttle(context, page);

  const started = Date.now();
  const inFlight = new Map();
  const api = [];
  let lastNetworkAt = started;
  const isApi = (request) => new URL(request.url()).pathname.startsWith("/api/");
  // A stream stays open for as long as the screen does; it is never "done".
  const isStream = (request) => ["eventsource", "websocket"].includes(request.resourceType());

  page.on("request", (request) => {
    if (isStream(request)) return;
    inFlight.set(request, Date.now());
    lastNetworkAt = Date.now();
  });
  const settle = async (request, failed) => {
    if (!inFlight.has(request)) return;
    const sent = inFlight.get(request);
    inFlight.delete(request);
    lastNetworkAt = Date.now();
    if (!isApi(request)) return;
    const response = failed ? null : await request.response().catch(() => null);
    const sizes = failed ? null : await request.sizes().catch(() => null);
    const url = new URL(request.url());
    api.push({
      method: request.method(),
      path: url.pathname + url.search,
      status: response ? response.status() : 0,
      bytes: sizes ? sizes.responseBodySize : 0,
      ms: Date.now() - sent,
      startedMs: sent - started,
    });
  };
  page.on("requestfinished", (request) => settle(request, false));
  page.on("requestfailed", (request) => settle(request, true));
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));

  await page.goto(`${origin}${screen.path}`, { waitUntil: "commit" });
  let headingMs = null;
  try {
    await page.locator("h1").first().waitFor({ timeout: TIMEOUT_MS });
    headingMs = Date.now() - started;
  } catch {
    // Recorded as a screen with no heading; the requests still say what it did.
  }
  // Settled: nothing in flight, nothing new for QUIET_MS, no loader showing.
  let loaderGoneMs = 0;
  let settled = false;
  while (Date.now() - started < TIMEOUT_MS) {
    if (inFlight.size === 0 && Date.now() - lastNetworkAt >= QUIET_MS) {
      const loading = await page
        .locator(LOADERS)
        .evaluateAll((nodes) => nodes.some((n) => n.getClientRects().length > 0))
        .catch(() => false);
      if (!loading) {
        settled = true;
        break;
      }
      loaderGoneMs = Date.now() - started;
    }
    await page.waitForTimeout(100);
  }
  const quietSince = lastNetworkAt - started;
  const usableMs =
    headingMs === null || !settled ? null : Math.max(headingMs, quietSince, loaderGoneMs);
  const shown = await page.locator("h1").first().innerText().catch(() => "");
  await page.close();
  return { usableMs, headingMs, settled, heading: shown.trim(), api, errors, pending: inFlight.size };
}

const server = await serve(dist, API);
const origin = `http://127.0.0.1:${server.address().port}`;
const browser = await chromium.launch();
const results = {};

try {
  const context = await browser.newContext(PHONE_CONTEXT);
  const { cookie } = await login({ api: API, origin, email: EMAIL, password: PASSWORD });
  await context.addCookies([cookie]);
  for (const screen of screens) {
    const runs = [];
    for (let i = 0; i < RUNS; i++) {
      runs.push(await measureOnce(context, origin, screen));
      // A screen that did not settle in TIMEOUT_MS will not in the next run
      // either; two more minutes of it measure nothing new.
      if (runs[0].usableMs === null) break;
    }
    const timed = runs.filter((r) => r.usableMs !== null);
    // The requests of the median run, so the bytes and the time are one run's.
    const middle = timed.length
      ? [...timed].sort((a, b) => a.usableMs - b.usableMs)[Math.floor(timed.length / 2)]
      : runs[0];
    results[screen.name] = {
      path: screen.path,
      heading: middle.heading,
      // A run that never settled counts as the slowest, not as missing.
      usableMs: timed.length * 2 > runs.length ? median(runs.map((r) => r.usableMs ?? Infinity)) : null,
      headingMs: timed.length ? median(timed.map((r) => r.headingMs)) : null,
      runs: runs.map((r) => r.usableMs),
      apiKiB: Number((middle.api.reduce((a, r) => a + r.bytes, 0) / 1024).toFixed(1)),
      api: middle.api.sort((a, b) => a.startedMs - b.startedMs),
      errors: [...new Set(runs.flatMap((r) => r.errors))],
    };
    const r = results[screen.name];
    const largest = Math.max(0, ...r.api.map((a) => a.bytes)) / 1024;
    console.log(
      `  ${screen.name.padEnd(24)} ${String(r.usableMs ?? "never").padStart(7)} ms usable  ` +
        `${String(r.api.length).padStart(3)} requests  ${r.apiKiB.toFixed(1).padStart(8)} KiB` +
        `  (largest ${largest.toFixed(1)} KiB)${r.heading ? "" : "  NO HEADING"}`,
      // "never": not settled within TIMEOUT_MS — still loading, or no heading.
    );
  }
} finally {
  await browser.close();
  server.close();
}

writeFileSync(OUT, `${JSON.stringify(results, null, 2)}\n`);
