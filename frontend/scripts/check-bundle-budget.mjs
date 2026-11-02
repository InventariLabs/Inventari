#!/usr/bin/env node
/**
 * The bundle size budget — the brake the start path never had.
 *
 * Measured when this budget was introduced: the entry path carried
 * ~389 KiB gzip of translations alone and grew linearly with the number of
 * modules, and nothing in the build failed when it did. This script reads
 * `dist/` the way a browser does — index.html, then the closure of its
 * static imports — and fails the build when the two paid paths outgrow
 * their budgets:
 *
 *   initial      — what a signed-out visitor downloads before anything
 *                  renders: index.html plus the closure of the entry chunk.
 *   appFirstPaint — the same plus the App tree's closure and the heaviest
 *                  single language file, which i18next preloads before the
 *                  first render. This is the signed-in reader's price.
 *
 * Chunk sizes drift a few KiB between builds; the budgets sit one step
 * above the measured values so ordinary churn stays green and a regression
 * — a new static import into the entry, a module sneaking back into the
 * startup path — does not.
 */
import { readFileSync, readdirSync, existsSync } from "node:fs";
import { gzipSync } from "node:zlib";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const dist = join(root, "dist");

/**
 * Budgets in KiB of gzip.
 *
 * Measured 2026-09-26, after the module translations and the
 * module registration left the startup path: initial 212.8, app first paint
 * 313.4 — against 196.8 / 740.8 measured on the dev tip this shipped from,
 * where the start path carried all five languages (473.0 KiB gz of it) and
 * every module's registration code. The budgets sit one step above what was
 * measured, so ordinary churn stays green and a regression — a new static
 * import into the entry, a module sneaking back into the startup path —
 * does not.
 *
 * Re-measured 2026-10-02 on the dev tip: initial 234.0, app first paint 335.9,
 * so initial moved from 230 to 240 — the start path had grown ~21 KiB in a
 * week of ordinary feature work, and the gate had never run outside the
 * production image, so nobody saw it grow. It now runs in `build:check`
 * (`make check-frontend`), not in `npm run build`: a size budget is a review
 * signal, and a production build that refuses to produce an image over a few
 * KiB stops a deploy for something no user would notice.
 *
 * Re-measured 2026-10-12: the dev tip stood at initial 239.9 / app first paint
 * 349.9, 0.1 KiB under both budgets, so the failed-load copy in five languages
 * (240.1 / 350.3) tipped them over with nothing wrong in the entry. Each moved
 * up one step, 240 to 245 and 350 to 355.
 *
 * Re-measured 2026-10-14: the dev tip stood at initial 240.4 / app first paint
 * 354.0; the error screens' copyable details (one component and two strings in
 * five languages) took it to 242.6 / 356.3, so app first paint moved up one
 * step, 355 to 360. The details sit in the error boundary, which has to ship
 * with the entry: a chunk that failed to load is the crash it reports.
 *
 * Re-measured 2026-10-17: the dev tip stood at initial 243.2 / app first paint
 * 360.0 (359.997); the short pick and receive dialogs' summary line and
 * replacement tick, merged with the deliberate skip confirmation, took it to
 * 360.1. The dialogs are opened from the session screens in the App tree, and
 * a window a worker opens on demand is not worth a lazy boundary of its own,
 * so app first paint moves up one step, 360 to 365. The picking batch toasts
 * (three strings in five languages) land in the per-language chunk every
 * first paint loads; with both changes merged the tree measures 360.3. The
 * product label copy in five languages adds 0.14 KiB gz of the Polish file,
 * the heaviest, to the start path, inside the same step: 243.4 / 360.5
 * measured on the merge with the label change.
 *
 * Re-measured 2026-10-20 on the merge: the warehouse start screen's copy —
 * four action tiles with their sentences, the To do count and footnote, and
 * the day feed's title, entry, empty states and error, in five languages —
 * took the start path to 365.1, and the Locations tab's shared form controls
 * took the merged tree to initial 243.6 / app first paint 366.6. The entry
 * path barely moved and the tab itself is a lazy chunk, so this is the
 * ordinary growth of the signed-in tree: app first paint moves one step,
 * 365 to 370, from the start screen's measurement.
 *
 * The undo action's copy (the warehouse module, loaded at first paint) and
 * counting a location (its screen, its setting and the due-count To do line,
 * in five languages) come on top, inside the same step: 243.6 / 366.7
 * measured on the merge of all three.
 *
 * Re-measured 2026-10-21 on the merge with the one-screen receive: the
 * receive sheet's copy — its fields, the line table, the paste notices and
 * the success panel, in five languages — lands in the documents language
 * file the first paint loads, and took the merged tree to initial 243.8 /
 * app first paint 370.2, 0.2 over the ceiling the dev tip had come to. app
 * first paint moves one step, 370 to 375.
 *
 * Re-measured 2026-10-21 on the merge of the work board and the stale-chunk
 * recovery: each branch stood under 370 alone (the dev tip 369.2, the board
 * 369.7, the recovery 369.6), together they measure initial 244.1 / app first
 * paint 370.2. The board's copy (columns, person chips, the custom-card form
 * and the measures strip, in five languages) and the failed-load copy both
 * sit in the per-language chunk every first paint loads, so app first paint
 * moves up one step, 370 to 375.
 *
 * Re-measured 2026-10-25 on the merge of the catalogue fixes and the kitchen
 * launch pass: the dev tip measured app first paint 375.0, exactly the
 * ceiling. The kitchen branch took it to 375.1 (initial 188.3, twice on each
 * side), and the catalogue branch's copy (the SKU label, the records count,
 * the import's "added to products you already have" line and the search
 * hit's per-product total, in five languages) added 0.2 KiB gz of the Polish
 * file, the heaviest, to the start path: 375.3 on its own. What grew is copy,
 * not an import: the reconciliation panel's new sentences and the "Choose a
 * unit" message of the recipe and shopping-list forms, and the catalogue's
 * labels, sit in the per-language chunk every first paint loads (the Polish
 * one, 133.0 KiB). App first paint moves up one step, 375 to 380.
 *
 * Re-measured 2026-10-25 on the merge of the backorder stock-cover badge, on
 * top of the catalogue step above: that merge stood at 375.3 against the new
 * ceiling of 380, and the three short sentences the badge adds to the To do
 * list ("can be issued in full", "in part", "nothing to issue yet"), in five
 * languages, sit in the warehouse copy of the per-language chunk every first
 * paint loads. They take the merged tree to initial 188.3 / app first paint
 * 375.9, still inside the ceiling the catalogue step set, so the number stays
 * at 380.
 *
 * Re-measured 2026-10-25 on the merge with the home-location question of the
 * put-away, after the two merges above: its copy (the question, the
 * three refusals, the settings choice and the list of products not asked
 * about, in five languages) sits in the warehouse language file every first
 * paint loads, and its sheet in the To do chunk the start screen opens. The
 * merged tree, the stock-cover badge in it, measures initial 188.3 / app
 * first paint 376.3, and on the phone login 381.0, launcher 395.9 and start
 * 606.8. App first paint, login and launcher stand under the ceilings the
 * dev tip already carries; only start crosses its 605, by 1.8 KiB — the sheet
 * in its own chunk, not an import that walked in — so that one ceiling moves
 * a step of five.
 *
 * Re-measured 2026-10-26 on the merge of the kitchen launch pass with that
 * put-away step: the kitchen copy sits on top of the 376.3 above and takes the
 * merged tree to app first paint 376.5, login 381.2, launcher 396.2 and start
 * 607.4 — every one inside the ceilings as they stand, so none moves.
 *
 * Re-measured 2026-10-26 on the branch that moved every location picker to a
 * server search: the picker, its two hooks and the by-id naming hook now sit
 * in the chunks of the screens that pick a place. App first paint (377.7),
 * login (382.4), launcher (397.3) and receive (447.0) stand under their
 * ceilings; start measures 611.1, issue 561.6, history 585.1 and products
 * 493.7, so those four phone budgets move one step of five: 615, 565, 590
 * and 495. The first-paint ceiling stays at 380.
 *
 * Re-measured 2026-10-25 on the merge of the office-output branch: its copy
 * (the scrap reason list and cost line, the register's scrap and unvalued
 * notes, the receive sheet's unpriced-line notice, the print layout rule, the
 * stock-value tile's lower-bound note, in five languages) lands in the
 * per-language chunk every first paint loads, 21 lines in the warehouse file
 * and 2 in the stats file, and took the tree to app first paint 375.4 on top
 * of a dev tip that stood at the ceiling. Merged with the backorder badge
 * above it measures initial 188.3 / app first paint 376.3, so the raise of
 * app first paint, 375 to 380, is the one the catalogue fixes already made
 * and it stays one step; the login and start phone budgets (385 and 610),
 * which carry that chunk, move with it.
 *
 * Re-measured 2026-10-26 after merging the development line again: the
 * document history screen, which also hosts the register with its scrap and
 * unvalued notes, measures 580.0 KiB gz against its 580 on a tree whose app
 * first paint is 376.4 (initial 188.3), so that one phone budget moves to
 * 585. The first-paint ceiling stays at 380.
 *
 * Re-measured 2026-10-26 on the merge with the community-languages change of
 * the development line: the merged tree measures initial 188.7 / app first
 * paint 377.3, both inside their ceilings, and on the phone the issue screen
 * 555.1 KiB gz against its 555 — the scrap reason list this branch adds to
 * that screen, in five languages, on top of the language files the first
 * paint loads. That one phone budget moves a step of five, to 560; the other
 * screens stand under theirs (login 382.0, launcher 397.0, start 609.2,
 * receive 446.1, history 580.9, products 489.0).
 *
 * Re-measured 2026-10-27 on the merge of the occupancy fix with the
 * development line: the dev tip alone measures the products screen at 489.9
 * KiB gz against its 490, and the occupancy screen's two new failure lines
 * (a search that could not be run, a location whose contents could not be
 * read), in five languages, sit in the warehouse language file every first
 * paint loads and take it to 490.0. That one phone budget moves a step of
 * five, to 495; the merged tree measures initial 188.7 / app first paint
 * 377.9, and the other screens stand under theirs (login 382.6, launcher
 * 397.5, start 609.9, receive 446.7, issue 555.5, history 581.5).
 *
 * Re-measured 2026-10-28 on the merge of the module-boundary change with the
 * development line: the dev tip alone measures the receive screen at 449.2
 * KiB gz against its 450, and the merged tree at 450.1. Modules that stopped
 * importing each other's files now take the card link, the composition bar,
 * the text area and the label client from @/module-sdk, and the bundler
 * keeps that barrel as one shared chunk that loads every module it
 * re-exports, so the receive screen, which loads the barrel, pays about 0.9
 * KiB for parts it never draws. That one phone budget moves a step of five,
 * to 455; the merged tree measures initial 188.9 / app first paint 379.6,
 * and the other screens stand under theirs (login 384.3, launcher 399.3,
 * start 612.6, issue 562.8, history 587.0, products 492.2).
 *
 * Re-measured 2026-10-29 on the merge of the audit journal's module writes
 * with the development line: the dev tip alone measures app first paint
 * 379.9, and the branch's labels for the fields its new journal entries
 * carry (eighteen of them, in six languages) sit in the common language
 * file every first paint loads, 0.2 KiB gz of the Polish one, and take the
 * merged tree to 380.2. App first paint moves one step, 380 to 385; the
 * merged tree measures initial 188.9, and the phone screens stand under
 * theirs (login 384.9, launcher 399.9, start 613.2, receive 450.7, issue
 * 563.4, history 587.6, products 492.8).
 *
 * Re-measured 2026-10-29 with equipment status confirmation and valuation
 * notices: their translations bring app first paint to 380.4 KiB gz and
 * phone login to 385.1, launcher to 400.1. Both phone ceilings move one
 * step of five; the remaining screens stay within their budgets.
 *
 * Re-measured 2026-10-29 on the merge of the contract-typing change with the
 * development line: the dev tip alone measures the login screen at 385.0 KiB
 * gz against its 385, and the document type now generated from the contract
 * adds the stock-count adjustment to the new-document label map, a few bytes
 * of the shared warehouse code the login chunk set carries. That one phone
 * budget moves a step of five, to 390; the merged tree measures app first
 * paint 380.3, and the other screens stand under theirs.
 *
 * Re-measured 2026-10-30 on the scan-answer branch with translated picking
 * and receiving scan answers:
 * the launcher carries the Polish copy and measures 400.1 KiB gz against
 * its 400 ceiling. Its budget moves one step to 405; app first paint is
 * 380.4 and the other phone screens remain within their budgets.
 *
 * Re-measured 2026-10-29 on the merge of the stock-take report's wording
 * with the development line: the tree without it measures the launcher at
 * 400.0 KiB gz against its 400, and the two labels the report gains (the
 * filter for differences and uncounted lines, the singular badge of an
 * uncounted row), in six languages, sit in the common language file every
 * first paint loads, a few bytes of the Polish one, which tips the launcher
 * over. That one phone budget moves a step of five, to 405; the merged tree
 * measures app first paint 380.3, and the other screens stand under theirs
 * (login 385.0, start 613.4, receive 450.9, issue 563.6, history 587.8,
 * products 493.0).
 *
 * Re-measured 2026-10-31 on the merge of the catalogue pre-publication pass
 * with the development line, wording pass included: the merged tree measures
 * the issue screen at 565.3 KiB gz against its 565 and the products screen at
 * 495.4 against its 495, the second after the branch's own additions (the
 * product page link, the wrong-label release in the Edit product sheet, the
 * unknown-code notice and their copy in six languages). Those two phone
 * budgets move a step of five, to 570 and 500; the start screen, at 616.2,
 * stands under the 620 set below. The same tree measures initial 188.9 / app
 * first paint 383.1, and the other screens stand under theirs (login 387.8,
 * launcher 402.8, receive 451.7, history 589.7).
 *
 * Re-measured 2026-10-31 on the warehouse floor's wording pass: the plain-word
 * rewrites (the hold's reason, the correction dialog, the putaway field,
 * History's subtitle), the write-off dialog's two sentences and the join
 * link's third card are copy in six languages, and the Polish one sits in
 * the language chunk the start screen loads. The write-off dialog itself is
 * loaded on the press, not on first paint; the tree measures start at
 * 615.4 KiB gz without it counted, 0.4 over its 615, with the other phone
 * screens under theirs. That one budget moves a step of five, to 620.
 *
 * Re-measured 2026-10-31 on the merge of the warehouse screens' regression
 * fixes with the development line: the dev tip alone measures issue at
 * 564.9 KiB gz against its 565, with app first paint 383.0. The branch's
 * copy (readable draft titles, the mark that tells a count's records apart,
 * the receive result's waiting-in-Receiving sentence and partner link, the
 * production sheet's reasons beside a disabled save, in six languages) sits
 * in the per-language chunk every first paint loads and takes app first
 * paint to 383.2 and issue to 565.2 — copy, not an import. That one phone
 * budget moves a step of five, to 570; the other screens stand under
 * theirs (login 387.9, launcher 402.9, start 616.1, receive 453.3, history
 * 589.7, products 494.5).
 *
 * The kitchen, approvals and statistics pass moved the same budget to the
 * same 570 for the same reason (its copy in the language chunk took issue to
 * 565.3 over a 564.9 tip). The merge of the two measures issue at 565.6 and
 * app first paint at 383.6, under the 570 and the 385 both set. The same
 * merge takes history to 590.2 KiB gz against its 590 and products to 495.1
 * against its 495: each branch's copy alone kept them under (dev tip 589.7
 * and 494.5), the two together add half a KiB to the language chunk every
 * first paint loads — copy, not an import. Those two budgets move a step of
 * five, to 595 and 500; the other screens stand under theirs (login 388.3,
 * launcher 403.3, start 616.5, receive 453.7).
 *
 * Re-measured 2026-10-31 on the merge of the first-contact and settings
 * wording with that line: the labels the branch adds to the same
 * per-language chunk (onboarding, scan-tab and audit wording) and the line's
 * own copy together take the history screen to 590.1 KiB gz against its
 * 590 — copy, not an import; the line alone measures 589.7. That one phone
 * budget moves a step of five, to 595; app first paint measures 383.5,
 * initial 189.0, and the other screens stand under theirs (login 388.2,
 * launcher 403.2, start 616.4, receive 453.6, issue 565.5, products 494.9).
 *
 * The two moves above meet on history, both to 595. Their merge measures
 * history at 590.5, products at 495.4 under the 500 the kitchen pass set,
 * issue 565.9, app first paint 383.9 and initial 189.0; the other screens
 * stand under theirs (login 388.6, launcher 403.5, start 616.8, receive
 * 454.0).
 *
 * Re-measured 2026-11-01 on the branch that ties the scanner's memory to its
 * owner: app first paint 385.06 KiB gz against its 385, over a dev tip at
 * 384.96 — 37 bytes from the line. The branch adds 101: the owner check in
 * the two stores every load imports (initial 189.02 to 189.10), and the
 * missing-category sentence in the Polish file. No import walked in; one
 * that had (the form memory store, into the auth store) was taken back out.
 * App first paint moves a step of five, to 390; the other screens stand under
 * theirs (login 389.8, launcher 404.8, start 618.4, receive 454.7, issue
 * 567.4, history 591.9, products 497.9).
 *
 * Re-measured 2026-11-02 on the branch where an order with no price says so
 * and the dialog behind its Confirm names a dead end: login, launcher and
 * receive each measure a fraction of a KiB over 390, 405 and 455, and app first
 * paint 385.3. The branch adds the Polish file's copy for it, 139.4 KiB gz in
 * all; no import walked in, and the dead-end sentences are the approvals
 * module's own rather than three new ones. Those three phone budgets move a
 * step of five, to 395, 410 and 460; the other screens stand under theirs
 * (start 618.7, issue 567.7, history 592.3, products 498.2).
 */
const BUDGETS = {
  initial: 245,
  appFirstPaint: 390,
};

/**
 * The phone budget, per screen: what a reader on a mid Android over slow 4G
 * downloads for each core screen, in KiB of gzip. `phone-budget.json` holds
 * the budgets and the recorded measurement they were set from; the load-time
 * half of it is enforced by `npm run perf:phone`, which needs a running stack
 * and a browser (`make check-frontend` runs it). The bytes need neither, so
 * they are checked here, on every build, from what `dist/` holds.
 */
const PHONE_BUDGET = JSON.parse(
  readFileSync(join(root, "scripts", "phone-budget.json"), "utf8"),
);

const KIB = 1024;
const kib = (bytes) => bytes / KIB;
const gz = (file) => kib(gzipSync(readFileSync(file)).length);

if (!existsSync(join(dist, "index.html"))) {
  console.error(
    `check-bundle-budget: ${dist}/index.html not found — build first.`,
  );
  process.exit(2);
}

const distDir = join(dist, "assets");
const html = readFileSync(join(dist, "index.html"), "utf8");

// The assets a browser must fetch with index.html before anything renders.
const initialRefs = [
  ...[...html.matchAll(/<script[^>]+src="([^"]+)"/g)].map((m) => m[1]),
  ...[
    ...html.matchAll(/<link[^>]+rel="modulepreload"[^>]+href="([^"]+)"/g),
  ].map((m) => m[1]),
  ...[...html.matchAll(/<link[^>]+rel="stylesheet"[^>]+href="([^"]+)"/g)].map(
    (m) => m[1],
  ),
];

// Chunk files import each other with relative specifiers; follow them to the
// full static closure of whatever the browser was handed.
function closure(refs) {
  const seen = new Set();
  const queue = refs.map((ref) => ref.replace(/^\/+/, ""));
  while (queue.length > 0) {
    const ref = queue.pop();
    if (seen.has(ref) || !ref.endsWith(".js")) continue;
    if (!existsSync(join(dist, ref))) continue;
    seen.add(ref);
    const source = readFileSync(join(dist, ref), "utf8");
    for (const match of source.matchAll(
      /(?:from|import)\s*\(?\s*["'](\.[^"']+\.js)["']/g,
    )) {
      queue.push(join(dirname(ref), match[1]));
    }
  }
  return [...seen].sort();
}

const initialFiles = closure(initialRefs);

// The App tree: lazy-loaded behind sign-in, paid at the app's first paint.
// Vite names the chunk after the module — App-<hash>.js.
const appChunk = readdirSync(distDir).find((name) =>
  /^App-[\w-]+\.js$/.test(name),
);
if (!appChunk) {
  console.error(
    "check-bundle-budget: no App-*.js chunk in dist/assets — unexpected build shape.",
  );
  process.exit(2);
}
const appFiles = closure([`assets/${appChunk}`]);

// One language file is preloaded before the first render; the heaviest is
// the honest number.
const languageFiles = readdirSync(distDir)
  .filter((name) => /^i18n-[a-z-]+[\w-]*\.js$/.test(name))
  .map((name) => ({ name, gzip: gz(join(distDir, name)) }))
  .sort((a, b) => b.gzip - a.gzip);

const initialKib = initialFiles.reduce((sum, f) => sum + gz(join(dist, f)), 0);
const appOnlyKib = appFiles
  .filter((f) => !initialFiles.includes(f))
  .reduce((sum, f) => sum + gz(join(dist, f)), 0);
const languageKib = languageFiles[0]?.gzip ?? 0;
const appFirstPaintKib = initialKib + appOnlyKib + languageKib;

// A screen's price is the signed-in first paint plus the closure of its own
// lazy chunks — the part nothing else on the way in had already paid for.
const chunkNamed = (prefix) =>
  readdirSync(distDir).find((name) =>
    new RegExp(`^${prefix}-[\\w-]+\\.js$`).test(name),
  );
const screenKib = {};
const screenErrors = [];
for (const [screen, { chunks }] of Object.entries(PHONE_BUDGET.screens)) {
  const paid = new Set([...initialFiles, ...appFiles]);
  let own = 0;
  for (const prefix of chunks) {
    const chunk = chunkNamed(prefix);
    if (!chunk) {
      screenErrors.push(`${screen}: no ${prefix}-*.js chunk in dist/assets`);
      continue;
    }
    for (const file of closure([`assets/${chunk}`])) {
      if (paid.has(file)) continue;
      paid.add(file);
      own += gz(join(dist, file));
    }
  }
  screenKib[screen] = appFirstPaintKib + own;
}

const report = (label, value, budget) => {
  const mark = value <= budget ? "ok  " : "OVER";
  console.log(
    `  ${mark}  ${label.padEnd(16)} ${value.toFixed(1).padStart(7)} KiB gz  (budget ${budget})`,
  );
};

console.log("check-bundle-budget:");
report("initial", initialKib, BUDGETS.initial);
report("appFirstPaint", appFirstPaintKib, BUDGETS.appFirstPaint);
console.log(
  `         heaviest language: ${languageFiles[0]?.name ?? "none"} ${languageKib.toFixed(1)} KiB gz; ` +
    `App chunk ${appChunk} adds ${appOnlyKib.toFixed(1)} KiB gz over initial`,
);

console.log(
  "  phone budget, JS per screen (first paint + the screen's chunks):",
);
for (const [screen, kibValue] of Object.entries(screenKib)) {
  report(screen, kibValue, PHONE_BUDGET.screens[screen].budget.jsKiB);
}

const breaches = Object.entries({
  initial: initialKib,
  appFirstPaint: appFirstPaintKib,
}).filter(([name, value]) => value > BUDGETS[name]);

const screenBreaches = Object.entries(screenKib).filter(
  ([screen, value]) => value > PHONE_BUDGET.screens[screen].budget.jsKiB,
);
if (screenErrors.length > 0 || screenBreaches.length > 0) {
  console.error(
    `\ncheck-bundle-budget: phone budget — ${[
      ...screenErrors,
      ...screenBreaches.map(
        ([screen, value]) =>
          `${screen} ${value.toFixed(1)} > ${PHONE_BUDGET.screens[screen].budget.jsKiB} KiB gz`,
      ),
    ].join("; ")}. A screen a worker opens on a phone got heavier.`,
  );
  process.exitCode = 1;
}

if (breaches.length > 0) {
  console.error(
    `\ncheck-bundle-budget: ${breaches
      .map(
        ([name, value]) =>
          `${name} ${value.toFixed(1)} > ${BUDGETS[name]} KiB gz`,
      )
      .join("; ")}. The startup path grew — find the import that walked in.`,
  );
  process.exit(1);
}
