#!/usr/bin/env node
/**
 * check-suppressions.mjs
 *
 * Every active suppression needs an owner and an expiry date.
 *
 * This is the cure for the cause rather than the symptom. knip.json carried
 * the comment "Reserved scaffolding for planned slices — do NOT delete without
 * checking the maker production and module RBAC designs first" above three
 * entries. Somebody knew a feature was unfinished and wrote it down in a
 * config file: no owner, no date, and nowhere that note would ever come back
 * in front of anyone. The suppression did exactly what it was for. It silenced
 * the tool, and it silenced the person too.
 *
 * The register lives in suppressions.json and is read here, never written by a
 * `--write-baseline` run. That is deliberate: the baselines are machine
 * snapshots refreshed wholesale, so metadata kept inside them would have to be
 * re-merged by every writer and would be one merge bug away from vanishing.
 * Keeping the register separate means regeneration cannot lose it — a
 * regenerated baseline that reintroduces an entry simply finds its record
 * still standing, and one that drops an entry leaves a record this gate
 * reports as removable.
 *
 *   node check-suppressions.mjs        # fail on unowned, undated or expired
 *   node check-suppressions.mjs --list # print what is currently silenced
 */
import { readFileSync, existsSync } from "node:fs";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = resolve(new URL("..", import.meta.url).pathname); // frontend/
const REGISTER_PATH = resolve(ROOT, "scripts/suppressions.json");

/**
 * Where suppressions live, and how to read each one out.
 *
 * `id` is what the register is keyed by: `<source>::<entry>`, stable across a
 * baseline regeneration because it names the finding, not its position.
 */
const SOURCES = [
  {
    name: "knip.json:ignore",
    file: "knip.json",
    read: (data) => data.ignore ?? [],
  },
  {
    name: "knip-baseline",
    file: "scripts/knip-baseline.json",
    read: (data) => data.issues ?? [],
  },
  {
    name: "route-reachability-baseline",
    file: "scripts/route-reachability-baseline.json",
    read: (data) => data.unreachable ?? [],
  },
  {
    name: "reachability-baseline",
    file: "scripts/reachability-baseline.json",
    read: (data) => data.unreachable ?? [],
  },
  {
    name: "i18n-keys-baseline",
    file: "scripts/i18n-keys-baseline.json",
    read: (data) => [
      ...(data.violations ?? []),
      ...(data.plural ?? []),
      ...(data.unused ?? []),
    ],
  },
];

/**
 * knip.json is JSONC — it carries `//` comments by design, including after a
 * value on the same line. Stripped by scanning rather than by pattern, because
 * a pattern cannot tell a comment from a `//` inside a string, and every entry
 * in that file is a path.
 */
export function stripJsonc(text) {
  let out = "";
  let inString = false;
  for (let i = 0; i < text.length; i++) {
    const char = text[i];
    if (inString) {
      out += char;
      if (char === "\\") out += text[++i] ?? "";
      else if (char === '"') inString = false;
      continue;
    }
    if (char === '"') {
      inString = true;
      out += char;
      continue;
    }
    if (char === "/" && text[i + 1] === "/") {
      while (i < text.length && text[i] !== "\n") i++;
      out += "\n";
      continue;
    }
    out += char;
  }
  return out.replace(/,(\s*[}\]])/g, "$1");
}

function readJsonc(path) {
  return JSON.parse(stripJsonc(readFileSync(path, "utf8")));
}

export function collectSuppressions(sources, load) {
  const found = [];
  for (const source of sources) {
    const data = load(source.file);
    if (!data) continue;
    for (const entry of source.read(data)) {
      found.push({
        id: `${source.name}::${entry}`,
        source: source.name,
        entry,
      });
    }
  }
  return found;
}

export function auditRegister(suppressions, register, today) {
  const errors = [];
  const recorded = register.suppressions ?? {};
  for (const { id, source, entry } of suppressions) {
    const record = recorded[id];
    if (!record) {
      errors.push(
        `${source} silences "${entry}" with no record in suppressions.json. ` +
          `Add { "owner", "expires", "reason" } under "${id}" — or remove the suppression.`,
      );
      continue;
    }
    if (!record.owner)
      errors.push(`suppressions.json → "${id}": names nobody.`);
    if (!record.reason)
      errors.push(`suppressions.json → "${id}": gives no reason.`);
    const expires = record.expires ? new Date(record.expires) : null;
    if (!expires || Number.isNaN(expires.valueOf()))
      errors.push(
        `suppressions.json → "${id}": expires must be a YYYY-MM-DD date.`,
      );
    else if (expires < today)
      errors.push(
        `suppressions.json → "${id}": expired on ${record.expires} — ` +
          `${record.owner ?? "nobody"} was to decide. Resolve it or move the date with a reason.`,
      );
  }
  const live = new Set(suppressions.map((s) => s.id));
  const stale = Object.keys(recorded).filter((id) => !live.has(id));
  return { errors, stale };
}

function main() {
  const load = (file) => {
    const path = resolve(ROOT, file);
    return existsSync(path) ? readJsonc(path) : null;
  };
  const suppressions = collectSuppressions(SOURCES, load);

  if (process.argv.includes("--list")) {
    for (const { id } of suppressions) console.log(id);
    process.exit(0);
  }

  const register = existsSync(REGISTER_PATH)
    ? JSON.parse(readFileSync(REGISTER_PATH, "utf8"))
    : { suppressions: {} };
  const { errors, stale } = auditRegister(suppressions, register, new Date());

  if (stale.length > 0) {
    console.log(
      `${stale.length} record(s) in suppressions.json no longer silence anything and can be removed:`,
    );
    for (const id of stale) console.log(`  - ${id}`);
  }

  if (errors.length > 0) {
    console.error(
      `\nSuppressions without an owner or a date (${errors.length}):`,
    );
    for (const error of errors) console.error(`  - ${error}`);
    process.exit(1);
  }

  console.log(
    `Every one of the ${suppressions.length} active suppression(s) has an owner and a live date.`,
  );
  process.exit(0);
}

if (
  process.argv[1] &&
  resolve(process.argv[1]) === fileURLToPath(import.meta.url)
) {
  main();
}
