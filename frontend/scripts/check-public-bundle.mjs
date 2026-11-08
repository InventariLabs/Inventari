#!/usr/bin/env node
/**
 * The anonymous tree must not reach the application.
 *
 * `/public/attestation/:token` is opened by an employee with no account, from
 * a link in an email, to tick off the equipment they hold. It used to be a
 * route inside `App`, whose first statement eagerly globs every `module.ts`
 * under `src/modules/` — so serving a list of ten asset names handed that
 * reader the whole product: the warehouse, the recipes, the approvals engine,
 * and the API clients and translations of modules whose data they have no
 * right to see.
 *
 * `Root.tsx` chooses between `PublicApp` and `App` from the path before
 * either is imported. That separation is invisible in the type checker and in
 * the tests — a single `import` re-joins the two bundles and nothing else
 * would complain — so it is checked here.
 *
 * Usage: node scripts/check-public-bundle.mjs
 */

import { readdirSync, readFileSync } from "node:fs";
import { join, resolve, relative } from "node:path";

import { specifiersOf, resolveSpecifier } from "./check-reachability.mjs";

const ROOT = resolve(new URL("..", import.meta.url).pathname);
const SRC = resolve(ROOT, "src");

/** Where the anonymous tree starts. */
const ENTRIES = ["PublicApp.tsx", "publicRoutes.ts"];

/**
 * What it must never reach, and why each one matters.
 */
const FORBIDDEN = [
  {
    path: "App.tsx",
    reason:
      "the application's route table — it eagerly globs every module.ts, so importing it pulls in every module",
  },
  {
    path: "lib/moduleRegistry.ts",
    reason:
      "the module registry — modules register themselves into it on import",
  },
  {
    pattern: /^modules\/[^/]+\/module\.ts$/,
    reason: "a module's registration file",
  },
];

function walk(dir, out = []) {
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const full = join(dir, entry.name);
    if (entry.isDirectory()) walk(full, out);
    else out.push(full);
  }
  return out;
}

const files = walk(SRC)
  .map((f) => relative(SRC, f))
  .filter((rel) => /\.tsx?$/.test(rel) && !rel.endsWith(".d.ts"));

const known = new Set(files);
const read = (rel) => readFileSync(join(SRC, rel), "utf8");

/** Every file the anonymous tree reaches, and the shortest path to each. */
function closureFrom(entries) {
  const via = new Map(entries.map((e) => [e, [e]]));
  const queue = [...entries];
  while (queue.length) {
    const rel = queue.shift();
    for (const spec of specifiersOf(read(rel))) {
      const target = resolveSpecifier(spec, rel, known);
      if (!target || via.has(target)) continue;
      via.set(target, [...via.get(rel), target]);
      queue.push(target);
    }
  }
  return via;
}

for (const entry of ENTRIES) {
  if (!known.has(entry)) {
    console.error(`public-bundle: entry point ${entry} does not exist`);
    process.exit(1);
  }
}

const via = closureFrom(ENTRIES);

const hits = [];
for (const [rel, path] of via) {
  for (const rule of FORBIDDEN) {
    const matched = rule.pattern ? rule.pattern.test(rel) : rule.path === rel;
    if (matched) hits.push({ rel, reason: rule.reason, path });
  }
}

if (hits.length > 0) {
  console.error(
    `public-bundle: the anonymous tree reaches ${hits.length} file(s) it must not.\n`,
  );
  for (const hit of hits) {
    console.error(`  ${hit.rel}\n    ${hit.reason}`);
    console.error(`    reached via: ${hit.path.join(" -> ")}\n`);
  }
  console.error(
    "A visitor with no account downloads everything on that path. Move the\n" +
      "shared piece into a file both trees can import, or keep it out of the\n" +
      "public one.",
  );
  process.exit(1);
}

console.log(
  `public-bundle: the anonymous tree reaches ${via.size} source file(s), ` +
    `none of them the module registry`,
);
