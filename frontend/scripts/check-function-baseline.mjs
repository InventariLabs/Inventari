#!/usr/bin/env node
/**
 * check-function-baseline.mjs
 *
 * A whole-file `complexity: "off"` does not say "this file is complex
 * enough already" — it says "nothing in this file is measured any more".
 * A baselined function could grow from 54 to 90 points for free, and a new
 * function added beside it was never measured at all. The file list was a
 * comment away from being the opposite of a gate.
 *
 * This turns it into a ratchet with the numbers in it. Every function the
 * baseline still needs appears in scripts/function-baseline.json with its
 * frozen complexity and length; a plain run re-lints exactly the relaxed
 * files with the limits switched back on and refuses any mismatch, in either
 * direction. Growing a frozen function, adding a new one above the limit,
 * paying a debt without recording it, and leaving an entry that silences
 * nothing are four different messages and four ways to fail.
 *
 * `--write-baseline` is the only writer. It never invents an entry: it
 * snapshots the functions that are above the limit right now. So the only
 * way to freeze a new debt is to run it and commit the new numbers, where a
 * reviewer sees them as a one-line diff saying the gate covers less than it
 * did.
 *
 *   node scripts/check-function-baseline.mjs                  # check
 *   node scripts/check-function-baseline.mjs --write-baseline # snapshot now
 */
import { existsSync, readFileSync, writeFileSync } from "node:fs";
import { relative, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";

import { ESLint } from "eslint";

const ROOT = resolve(new URL("..", import.meta.url).pathname); // frontend/
const BASELINE_PATH = resolve(ROOT, "scripts/function-baseline.json");

/**
 * The two rules a function-level baseline covers. `blockName` is the `name`
 * of the whole-file override in eslint.config.js — the gate reads the file
 * list from there, so the two cannot drift apart silently: a file the config
 * relaxes but the baseline knows nothing about fails the run.
 */
export const COMPLEXITY = {
  key: "complexity",
  label: "complexity",
  ruleId: "complexity",
  blockName: "baseline:complexity-function-ratchet",
  pattern: /^(.*?) has a complexity of (\d+)\./,
};

export const MAX_LINES = {
  key: "maxLinesPerFunction",
  label: "max-lines-per-function",
  ruleId: "max-lines-per-function",
  blockName: "baseline:max-lines-per-function-ratchet",
  pattern: /^(.*?) has too many lines \((\d+)\)\./,
};

export const RULES = [COMPLEXITY, MAX_LINES];

/**
 * From "Function 'StatsPage'" to "StatsPage".
 *
 * ESLint names a function by its declaration, and refuses to invent one for
 * an arrow assigned to a variable: those come through as the bare kind,
 * "Arrow function". Two of one kind in a file share a name — `compareRule`
 * compares their values as a multiset, so one growing still fails even when
 * the other shrank.
 */
export function bareName(kind) {
  const quoted = /^(.*?) '(.+)'$/.exec(kind);
  return quoted ? quoted[2] : kind;
}

/**
 * ESLint results → `{ file: { function: [values] } }`, paths relative to the
 * frontend root and values sorted. Only messages of `rule` are read; any
 * other finding is some other gate's business.
 */
export function parseViolations(results, rule, root) {
  const snapshot = {};
  for (const result of results) {
    const file = relative(root, result.filePath).split(sep).join("/");
    for (const message of result.messages) {
      if (message.ruleId !== rule.ruleId) continue;
      const match = rule.pattern.exec(message.message);
      if (!match) continue;
      const name = bareName(match[1]);
      snapshot[file] ??= {};
      snapshot[file][name] ??= [];
      snapshot[file][name].push(Number(match[2]));
    }
  }
  for (const file of Object.keys(snapshot)) {
    for (const name of Object.keys(snapshot[file])) {
      snapshot[file][name].sort((a, b) => a - b);
    }
  }
  return snapshot;
}

/**
 * One rule's measured snapshot against its frozen one. Returns the reasons
 * they differ, each naming the file, the function and which direction the
 * number moved.
 */
export function compareRule(label, measured, frozen) {
  const errors = [];
  const files = [
    ...new Set([...Object.keys(measured), ...Object.keys(frozen)]),
  ].sort();

  for (const file of files) {
    const now = measured[file] ?? {};
    const was = frozen[file] ?? {};
    const names = [...new Set([...Object.keys(now), ...Object.keys(was)])].sort();

    for (const name of names) {
      const have = [...(now[name] ?? [])];
      const want = [...(was[name] ?? [])];

      if (!(name in was)) {
        for (const value of have) {
          errors.push(
            `${file} → ${name}: ${label} ${value} is above the limit and not in ` +
              `the baseline. New code must comply — split the function, or freeze ` +
              `it explicitly with --write-baseline.`,
          );
        }
        continue;
      }
      if (!(name in now)) {
        for (const value of want) {
          errors.push(
            `${file} → ${name}: frozen at ${label} ${value}, which no longer ` +
              `stands. Drop it with --write-baseline — the ratchet only turns down.`,
          );
        }
        continue;
      }

      // Equal values cancel out; what is left moved, appeared or vanished.
      const remaining = [...want];
      const extra = [];
      for (const value of have) {
        const at = remaining.indexOf(value);
        if (at >= 0) remaining.splice(at, 1);
        else extra.push(value);
      }
      const paired = Math.min(extra.length, remaining.length);
      for (let i = 0; i < paired; i++) {
        if (extra[i] > remaining[i]) {
          errors.push(
            `${file} → ${name}: ${label} grew from ${remaining[i]} to ${extra[i]}. ` +
              `Bring it back under ${remaining[i]}, or freeze the new value with ` +
              `--write-baseline so the diff shows the debt grew.`,
          );
        } else {
          errors.push(
            `${file} → ${name}: ${label} dropped from ${remaining[i]} to ` +
              `${extra[i]} — debt paid. Lock the gain with --write-baseline, or ` +
              `the room it left is spent by the next addition with no diff to ` +
              `show it.`,
          );
        }
      }
      for (const value of extra.slice(paired)) {
        errors.push(
          `${file} → ${name}: one more ${label} of ${value} than the baseline ` +
            `freezes. New code must comply, or freeze it explicitly with ` +
            `--write-baseline.`,
        );
      }
      for (const value of remaining.slice(paired)) {
        errors.push(
          `${file} → ${name}: frozen at ${label} ${value}, which no longer ` +
            `stands. Drop it with --write-baseline — the ratchet only turns down.`,
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
    for (const name of Object.keys(snapshot[file]).sort()) {
      sorted[file][name] = [...snapshot[file][name]].sort((a, b) => a - b);
    }
  }
  return sorted;
}

/**
 * The whole-file overrides, with their `"off"` replaced by the limits the
 * main config sets. Read from the config itself rather than copied here, so
 * raising a limit in eslint.config.js raises the ratchet's ceiling with it —
 * there is no second number to forget.
 */
function measureConfig(config) {
  const relaxed = new Map();
  for (const rule of RULES) {
    const block = config.find((entry) => entry.name === rule.blockName);
    if (!block) {
      throw new Error(
        `eslint.config.js has no "${rule.blockName}" block — the ratchet has ` +
          `nothing to read its file list from.`,
      );
    }
    const limit = config.find((entry) => Array.isArray(entry.rules?.[rule.ruleId]))
      ?.rules[rule.ruleId];
    if (!limit) {
      throw new Error(
        `eslint.config.js sets no ${rule.ruleId} limit to re-apply to the baseline.`,
      );
    }
    relaxed.set(rule.blockName, { ruleId: rule.ruleId, limit });
  }
  return config.map((entry) => {
    const override = relaxed.get(entry.name);
    return override
      ? { ...entry, rules: { [override.ruleId]: override.limit } }
      : entry;
  });
}

async function main() {
  const writeBaseline = process.argv.includes("--write-baseline");
  const config = (await import("../eslint.config.js")).default;
  const frozen = existsSync(BASELINE_PATH)
    ? JSON.parse(readFileSync(BASELINE_PATH, "utf8"))
    : {};

  const eslint = new ESLint({
    cwd: ROOT,
    overrideConfigFile: true,
    overrideConfig: measureConfig(config),
  });

  const measured = {};
  const errors = [];

  for (const rule of RULES) {
    const block = config.find((entry) => entry.name === rule.blockName);
    const listed = block.files ?? [];
    const missing = listed.filter((file) => !existsSync(resolve(ROOT, file)));
    const present = listed.filter((file) => existsSync(resolve(ROOT, file)));
    const results = present.length ? await eslint.lintFiles(present) : [];
    const snapshot = parseViolations(results, rule, ROOT);
    measured[rule.key] = snapshot;

    for (const file of missing) {
      errors.push(
        `${file} is relaxed for ${rule.label} in eslint.config.js, but the ` +
          `file no longer exists — remove it from the list.`,
      );
    }
    for (const file of present) {
      if (!snapshot[file]) {
        errors.push(
          `${file} is relaxed for ${rule.label} in eslint.config.js, but no ` +
            `function in it is above the limit — remove the file from the ` +
            `list; the ratchet only turns down.`,
        );
      }
    }
    for (const file of Object.keys(frozen[rule.key] ?? {})) {
      if (!listed.includes(file)) {
        errors.push(
          `scripts/function-baseline.json freezes ${rule.label} in ${file}, ` +
            `which eslint.config.js no longer relaxes — drop it with ` +
            `--write-baseline.`,
        );
      }
    }
    errors.push(...compareRule(rule.label, snapshot, frozen[rule.key] ?? {}));
  }

  if (writeBaseline) {
    const body = {
      generatedBy: "node scripts/check-function-baseline.mjs --write-baseline",
      note:
        "Per-function debt frozen because the whole-file eslint override for " +
        "that rule is still needed. A plain run of " +
        "scripts/check-function-baseline.mjs fails on any mismatch in either " +
        "direction; this snapshot is the only writer.",
      complexity: sortSnapshot(measured[COMPLEXITY.key]),
      maxLinesPerFunction: sortSnapshot(measured[MAX_LINES.key]),
    };
    writeFileSync(BASELINE_PATH, `${JSON.stringify(body, null, 2)}\n`);
    const count = RULES.reduce(
      (sum, rule) => sum + Object.keys(measured[rule.key]).length,
      0,
    );
    console.log(
      `function-baseline.json written: ${count} file(s) across ` +
        `${RULES.length} rule(s). Run the check without --write-baseline to ` +
        `see what the config's file lists must drop.`,
    );
    process.exit(0);
  }

  if (errors.length > 0) {
    console.error(
      `\nFunction baseline drifted (${errors.length}):\n`,
    );
    for (const error of errors) console.error(`  - ${error}`);
    console.error(
      `\nThe frozen values live in scripts/function-baseline.json; the file ` +
        `lists they cover live in eslint.config.js.`,
    );
    process.exit(1);
  }

  const count = RULES.reduce(
    (sum, rule) => sum + Object.keys(measured[rule.key]).length,
    0,
  );
  console.log(
    `Function baseline holds: ${count} relaxed file(s), every frozen ` +
      `function's ${RULES.map((rule) => rule.label).join(" and ")} unchanged.`,
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
