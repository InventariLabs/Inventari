#!/usr/bin/env node
/**
 * check-a11y-baseline.mjs
 *
 * The jsx-a11y rules are on for every product component. A file that already
 * held a finding when they were switched on is relaxed in eslint.config.js —
 * and a whole-file "off" says "nothing in this file is measured any more": a
 * second missing label next to the first would pass unseen.
 *
 * This turns the relaxation into a ratchet with the numbers in it. The
 * findings of every relaxed file are frozen in scripts/a11y-baseline.json,
 * one count per file and rule. A plain run lints the whole tree with the
 * relaxation dropped and refuses any mismatch, in either direction: a file
 * gaining a finding, a file with findings that is not listed, and an entry
 * that silences nothing are three different messages. The list of relaxed
 * files is read from the same JSON by eslint.config.js, so the two cannot
 * drift apart.
 *
 * `--write-baseline` is the only writer. It never invents an entry: it
 * snapshots what the rules report right now, so freezing a new debt is a
 * commit a reviewer sees as a line saying the gate covers less than before.
 *
 *   node scripts/check-a11y-baseline.mjs                  # check
 *   node scripts/check-a11y-baseline.mjs --write-baseline # snapshot now
 */
import { existsSync, readFileSync, writeFileSync } from "node:fs";
import { relative, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";

import { ESLint } from "eslint";

const ROOT = resolve(new URL("..", import.meta.url).pathname); // frontend/
const BASELINE_PATH = resolve(ROOT, "scripts/a11y-baseline.json");
const BLOCK_NAME = "baseline:jsx-a11y-ratchet";

/**
 * ESLint results → `{ file: { rule: count } }`, paths relative to the
 * frontend root. Only jsx-a11y findings are read; any other finding is some
 * other gate's business.
 */
export function parseViolations(results, root) {
  const snapshot = {};
  for (const result of results) {
    const file = relative(root, result.filePath).split(sep).join("/");
    for (const message of result.messages) {
      if (!message.ruleId?.startsWith("jsx-a11y/")) continue;
      snapshot[file] ??= {};
      snapshot[file][message.ruleId] = (snapshot[file][message.ruleId] ?? 0) + 1;
    }
  }
  return snapshot;
}

/**
 * The measured snapshot against the frozen one. Returns the reasons they
 * differ, each naming the file and rule and which direction the count moved.
 */
export function compareSnapshots(measured, frozen) {
  const errors = [];
  const files = [
    ...new Set([...Object.keys(measured), ...Object.keys(frozen)]),
  ].sort();

  for (const file of files) {
    const now = measured[file] ?? {};
    const was = frozen[file] ?? {};
    const rules = [...new Set([...Object.keys(now), ...Object.keys(was)])].sort();

    for (const rule of rules) {
      const have = now[rule] ?? 0;
      const want = was[rule] ?? 0;
      if (have === want) continue;
      if (want === 0) {
        errors.push(
          `${file} → ${rule}: ${have} finding(s) not in the baseline. New ` +
            `markup must comply — fix it, or freeze it explicitly with ` +
            `--write-baseline so the diff shows the debt grew.`,
        );
      } else if (have === 0) {
        errors.push(
          `${file} → ${rule}: frozen at ${want}, which no longer stands. ` +
            `Drop it with --write-baseline — the ratchet only turns down.`,
        );
      } else if (have > want) {
        errors.push(
          `${file} → ${rule}: grew from ${want} to ${have}. Bring it back ` +
            `to ${want}, or freeze the new count with --write-baseline so ` +
            `the diff shows the debt grew.`,
        );
      } else {
        errors.push(
          `${file} → ${rule}: dropped from ${want} to ${have} — debt paid. ` +
            `Lock the gain with --write-baseline, or the room it left is ` +
            `spent by the next addition with no diff to show it.`,
        );
      }
    }
  }
  return errors;
}

/** Deterministic shape for the written file, and for comparing two runs. */
export function sortSnapshot(snapshot) {
  const sorted = {};
  for (const file of Object.keys(snapshot).sort()) {
    sorted[file] = {};
    for (const rule of Object.keys(snapshot[file]).sort()) {
      sorted[file][rule] = snapshot[file][rule];
    }
  }
  return sorted;
}

async function main() {
  const writeBaseline = process.argv.includes("--write-baseline");
  const config = (await import("../eslint.config.js")).default;
  const frozen = existsSync(BASELINE_PATH)
    ? JSON.parse(readFileSync(BASELINE_PATH, "utf8")).files
    : {};

  // The relaxation dropped: the baseline's own files are measured with the
  // rules on, like everything else.
  const eslint = new ESLint({
    cwd: ROOT,
    overrideConfigFile: true,
    overrideConfig: config.filter((entry) => entry.name !== BLOCK_NAME),
  });
  const results = await eslint.lintFiles(["src/**/*.tsx"]);
  const measured = parseViolations(results, ROOT);

  if (writeBaseline) {
    const body = {
      generatedBy: "node scripts/check-a11y-baseline.mjs --write-baseline",
      note:
        "jsx-a11y findings frozen because the whole-file eslint relaxation " +
        "for these files is still needed. A plain run of " +
        "scripts/check-a11y-baseline.mjs fails on any mismatch in either " +
        "direction; this snapshot is the only writer.",
      files: sortSnapshot(measured),
    };
    writeFileSync(BASELINE_PATH, `${JSON.stringify(body, null, 2)}\n`);
    console.log(
      `a11y-baseline.json written: ${Object.keys(measured).length} file(s). ` +
        `Run eslint again: the config reads its relaxed file list from it.`,
    );
    process.exit(0);
  }

  const errors = compareSnapshots(measured, frozen);
  if (errors.length > 0) {
    console.error(`\nAccessibility baseline drifted (${errors.length}):\n`);
    for (const error of errors) console.error(`  - ${error}`);
    console.error(
      `\nThe frozen counts live in scripts/a11y-baseline.json, which ` +
        `eslint.config.js also reads for the files it relaxes.`,
    );
    process.exit(1);
  }

  console.log(
    `Accessibility baseline holds: ${Object.keys(measured).length} relaxed ` +
      `file(s), every frozen jsx-a11y count unchanged.`,
  );
  process.exit(0);
}

if (
  process.argv[1] &&
  resolve(process.argv[1]) === fileURLToPath(import.meta.url)
) {
  main().catch((error) => {
    console.error(error);
    process.exit(1);
  });
}
