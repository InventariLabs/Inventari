#!/usr/bin/env node
/**
 * UI pattern report — every detector, counts per class, never blocking.
 *
 * The point is comparability. A cleanup that touches a hundred call sites is
 * only visible as a number going down, and until now each review re-derived
 * that number with a fresh grep, so two reviews could not be compared and a
 * class looked drained when the search had merely narrowed.
 *
 *   npm run scan:ui           counts per pattern
 *   npm run scan:ui -- --list every finding, with the sentence explaining it
 */
import { BLOCKING, DETECTORS } from "./ui-patterns/index.mjs";
import { scriptFiles, sourceFiles } from "./ui-patterns/lib.mjs";

const listFindings = process.argv.includes("--list");
const files = sourceFiles();
const scripts = scriptFiles();

const rows = DETECTORS.map((detector) => ({
  detector,
  ...detector.run(detector.corpus === "scripts" ? scripts : files),
}));

const width = Math.max(...rows.map((row) => row.detector.name.length));

console.log(
  `scan:ui — ${files.length} non-test .tsx files under src/, ` +
    `${scripts.length} counting .ts for the rules that read hooks too\n`,
);

for (const { detector, considered, findings } of rows) {
  console.log(
    `${detector.name.padEnd(width)}  ${String(findings.length).padStart(4)} ` +
      `finding(s) in ${String(considered).padStart(3)} candidate file(s)  ` +
      `${BLOCKING.has(detector.name) ? "[blocking]" : "[report]"}`,
  );
}

if (!listFindings) {
  console.log("\nRun with --list to see the findings and why each is one.");
  process.exit(0);
}

for (const { detector, findings } of rows) {
  if (findings.length === 0) continue;
  console.log(`\n${detector.name} — ${findings.length} finding(s)`);
  console.log(`  ${detector.says}\n`);
  for (const finding of findings) console.log(`  src/${finding}`);
}
