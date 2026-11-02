#!/usr/bin/env node
/**
 * UI convention gate — rules that a type-checker cannot see and that a review
 * keeps missing, because the offending code *looks* correct.
 *
 * The rules are not written here. They live in `ui-patterns/`, next to the
 * detectors that only report, because a gate and a report that describe the
 * same mistake in two places drift: the report ends up seeing the class and
 * the gate the one incident that created it. This file decides which of them
 * stop a commit — `ui-patterns/index.mjs` explains what earns a rule that
 * promotion, and `npm run scan:ui` shows the rest.
 */
import { BLOCKING, DETECTORS } from "./ui-patterns/index.mjs";
import { scriptFiles, sourceFiles } from "./ui-patterns/lib.mjs";

const files = sourceFiles();
const scripts = scriptFiles();
const enforced = DETECTORS.filter((detector) => BLOCKING.has(detector.name));

const summary = [];
let failed = false;

for (const detector of enforced) {
  const { considered, findings } = detector.run(
    detector.corpus === "scripts" ? scripts : files,
  );
  summary.push(`${detector.name} ${considered} file(s)`);
  if (findings.length === 0) continue;

  failed = true;
  console.error(`\n${detector.name}: ${detector.says}\n`);
  console.error(`${detector.advice}\n`);
  for (const finding of findings) console.error(`  src/${finding}`);
  console.error("");
}

if (failed) process.exit(1);

console.log(`ui-conventions: ${summary.join(", ")}, 0 violations`);
