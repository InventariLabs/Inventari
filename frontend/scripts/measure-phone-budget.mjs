#!/usr/bin/env node
/**
 * How the core screens feel on a warehouse phone, measured.
 *
 * A small firm works from a mid Android on weak signal, and nothing measured
 * how the application behaves there. This opens each core screen cold in
 * Chromium with the CPU slowed 4x and the network held to slow 4G (1.6 Mbit/s,
 * 150 ms round trip — the profile Lighthouse calls "Slow 4G"), and records
 * two numbers per screen:
 *
 *   loadMs — from the navigation until the screen's heading is on the page
 *            (the receive dialog for `receive`), the median of several runs.
 *   wireKiB — what the scripts weighed on the wire, gzip, as the production
 *            server sends them, until the network went idle. Information
 *            only: it moves with the data, so no budget is read against it
 *            (the budgeted figure is `budget.jsKiB`, read from `dist/`).
 *
 * The phone itself — the throttling, the viewport, the server of `dist/` — is
 * `phone-profile.mjs`, shared with the warehouse-scale measurement. So:
 *
 *   npm run build                       # the production bundle
 *   PHONE_BUDGET_API=http://127.0.0.1:8000 npm run perf:phone
 *   npm run perf:phone -- --record      # also rewrite `measured` in the file
 *
 * The budgets live in `phone-budget.json`. The bytes half is enforced on every
 * build by `check-bundle-budget.mjs` (`make check-frontend`), from `dist/`
 * alone. The time half is enforced here, and `make check-frontend` runs it as
 * its last step (`make perf-phone` on its own) against the running stack. The
 * load-time budgets sit 1.5x above what was measured, because a timing,
 * unlike a byte count, drifts. A shared host drifts it most: with the fleet's
 * suites running beside it, a screen that is not slower has measured twice its
 * median. So a screen over its budget is measured once more and keeps the
 * better median, and the report names the host's load next to the figures —
 * a failure on a loaded host is to be read against `origin/dev` on that same
 * host before it is read as a regression. The byte budgets know no such
 * allowance. It posts the onboarding setup (equipment_wms)
 * to the stack it is pointed at, as a freshly reset database needs it.
 */
import { existsSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "@playwright/test";
import {
  hostLoad,
  login,
  median,
  PHONE_CONTEXT,
  scriptBytes,
  serve,
  throttle,
} from "./phone-profile.mjs";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const dist = join(root, "dist");
const budgetFile = join(root, "scripts", "phone-budget.json");
const budget = JSON.parse(readFileSync(budgetFile, "utf8"));

const API = process.env.PHONE_BUDGET_API ?? "http://127.0.0.1:8000";
const EMAIL = process.env.DEV_ADMIN_EMAIL ?? "admin@example.com";
const PASSWORD = process.env.DEV_ADMIN_PASSWORD ?? "Admin123";
const RUNS = Number(process.env.PHONE_BUDGET_RUNS ?? 3);
const record = process.argv.includes("--record");

/** screen -> where it lives and what shows it is up. */
const SCREENS = {
  login: { path: "/login", signedIn: false },
  launcher: { path: "/", signedIn: true },
  start: { path: "/warehouse/todo", signedIn: true },
  receive: {
    // Receive is one screen of its own since the one-screen redesign; the
    // Start screen's first tile navigates there rather than opening a dialog.
    path: "/warehouse/receive",
    signedIn: true,
  },
  issue: { path: "/warehouse/issue", signedIn: true },
  history: { path: "/warehouse/history", signedIn: true },
  products: { path: "/inventory/items", signedIn: true },
};

async function measureOnce(context, origin, screen) {
  const { path, act } = SCREENS[screen];
  const page = await context.newPage();
  await throttle(context, page);

  const wireBytes = scriptBytes(page);

  const trouble = [];
  page.on("pageerror", (error) => trouble.push(`pageerror: ${error.message}`));
  page.on("requestfailed", (r) => trouble.push(`failed: ${r.url()} ${r.failure()?.errorText}`));
  page.on("response", (r) => r.status() >= 400 && trouble.push(`${r.status()}: ${r.url()}`));

  const started = Date.now();
  await page.goto(`${origin}${path}`, { waitUntil: "commit" });
  await page
    .locator("h1")
    .first()
    .waitFor({ timeout: 60_000 })
    .catch(async (error) => {
      // What the screen showed instead says more than the timeout does.
      const shown = await page.locator("body").innerText().catch(() => "");
      throw new Error(
        `${screen}: no heading after 60 s.\n${error.message}\nbody: ${shown.slice(0, 300)}\n${trouble.join("\n")}`,
      );
    });
  if (act) await act(page);
  const loadMs = Date.now() - started;
  // Scripts still in flight at this point are the ones a reader is waiting on
  // only if they delay the screen; count what had arrived.
  await page.waitForLoadState("networkidle", { timeout: 120_000 }).catch(() => {});
  const wireKiB = (await wireBytes()) / 1024;
  await page.close();
  return { loadMs, wireKiB };
}

// Chromium aborts every request in flight with ERR_NETWORK_CHANGED when the
// host's network changes, and on a machine that runs docker, starting another
// compose stack is enough. That run measured nothing; take it again.
async function measureWithRetry(context, origin, screen, attempts = 3) {
  for (let attempt = 1; ; attempt++) {
    try {
      return await measureOnce(context, origin, screen);
    } catch (error) {
      if (attempt >= attempts || !/ERR_NETWORK_CHANGED/.test(error.message)) {
        throw error;
      }
    }
  }
}

if (!existsSync(join(dist, "index.html"))) {
  console.error("perf:phone: dist/index.html not found — run `npm run build` first.");
  process.exit(2);
}

const server = await serve(dist, API);
const origin = `http://127.0.0.1:${server.address().port}`;
const browser = await chromium.launch();
const results = {};
const retried = new Set();
// The load before and after the run, the higher of the two: a minute's
// average taken only at the end misses a run that was busy at its start.
let host = hostLoad();

try {
  const anonymous = await browser.newContext(PHONE_CONTEXT);
  const signedIn = await browser.newContext(PHONE_CONTEXT);
  const { cookie } = await login({ api: API, origin, email: EMAIL, password: PASSWORD });
  await signedIn.addCookies([cookie]);

  for (const screen of Object.keys(SCREENS)) {
    const context = SCREENS[screen].signedIn ? signedIn : anonymous;
    const measureScreen = async () => {
      const runs = [];
      for (let i = 0; i < RUNS; i++) {
        runs.push(await measureWithRetry(context, origin, screen));
      }
      return {
        loadMs: median(runs.map((r) => r.loadMs)),
        wireKiB: Number(median(runs.map((r) => r.wireKiB)).toFixed(1)),
      };
    };
    results[screen] = await measureScreen();
    if (results[screen].loadMs > budget.screens[screen].budget.loadMs) {
      // One outlier median on a busy host is not a slower screen; a second
      // one over the budget is what fails the gate.
      retried.add(screen);
      const again = await measureScreen();
      if (again.loadMs < results[screen].loadMs) results[screen] = again;
    }
  }
} finally {
  await browser.close();
  server.close();
}
const after = hostLoad();
if (after.load > host.load) host = after;

let failed = false;
console.log(
  `perf:phone (${budget.profile.device}; ${budget.profile.network}; median of ${RUNS}; ` +
    `host load ${host.load.toFixed(1)} on ${host.cores} cores${host.loaded ? ", LOADED" : ""}):`,
);
for (const [screen, got] of Object.entries(results)) {
  const limit = budget.screens[screen].budget.loadMs;
  const over = got.loadMs > limit;
  failed ||= over;
  console.log(
    `  ${over ? "OVER" : "ok  "}  ${screen.padEnd(10)} ${String(got.loadMs).padStart(6)} ms ` +
      `(budget ${limit})  ${got.wireKiB.toFixed(1).padStart(6)} KiB js on the wire` +
      (retried.has(screen) ? "  (measured twice, the better median)" : ""),
  );
}

if (record) {
  const date = new Date().toISOString().slice(0, 10);
  for (const [screen, got] of Object.entries(results)) {
    budget.screens[screen].measured = { ...got, date, runs: RUNS };
  }
  writeFileSync(budgetFile, `${JSON.stringify(budget, null, 2)}\n`);
  console.log("perf:phone: measured numbers recorded in scripts/phone-budget.json");
}

if (failed) {
  console.error("\nperf:phone: a screen loads slower than its budget on the phone profile.");
  if (host.loaded) {
    console.error(
      `perf:phone: the host was loaded (load ${host.load.toFixed(1)} on ${host.cores} cores), ` +
        "which stretches every timing here; run the same gate on origin/dev on this host " +
        "before reading this as a regression of the branch.",
    );
  }
  process.exit(1);
}
