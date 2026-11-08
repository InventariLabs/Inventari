#!/usr/bin/env node
/**
 * check-vocabulary.mjs
 *
 * The English catalogs name each core concept with one word, and the words
 * that lost are not written again.
 *
 * `docs/MODULE_NAMES.md` ("Domain vocabulary") holds the table: one winning
 * word per concept and the words it retires. This gate is the half that
 * stops the retired words coming back. Name drift in this app was never a
 * single slip but layers from successive purposes — a fridge, an IT desk, a
 * warehouse — and each new feature that is copied from an old screen brings
 * the old layer's word with it.
 *
 * A retired word is a finding when it appears in an English catalog string
 * (`src/i18n/locales/en/*.json`, `src/modules/<name>/i18n/en.json`), unless
 * the rule exempts the string. The strings that already used a retired word
 * when the gate was written sit in `vocabulary-baseline.json`, keyed by file
 * and key path with the text they held. A baseline entry shields only that
 * exact text: change the string and it is a new or changed string again, so
 * it must be fixed before it can stay.
 *
 * The other four languages are not scanned. The table names their words, but
 * a word list does not carry across languages (Polish "miejsce" is retired as
 * the container and fine as "space on a shelf"), so the rule that reads them
 * is the review that reads the table.
 *
 * Modes:
 *   node check-vocabulary.mjs                    # report and exit 1
 *   node check-vocabulary.mjs --baseline         # only NEW or CHANGED strings fail
 *   node check-vocabulary.mjs --write-baseline   # snapshot current
 *   node check-vocabulary.mjs --quiet            # exit code only
 *
 * Baseline: frontend/scripts/vocabulary-baseline.json
 * The goal is an empty baseline. An entry is a module screen the sweep of the
 * core screens did not reach.
 */
import { existsSync, readdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join, relative, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const SRC = join(ROOT, "src");
const BASELINE_PATH = join(ROOT, "scripts/vocabulary-baseline.json");

/**
 * One rule per retired family. `use` is what the sentence should say instead.
 * `exempt` regexes blank a legitimate use of the same letters before the
 * pattern is tried; `skipFiles` excuses a whole catalog where the word names
 * a different act; `skipKeys` (matched against `file::path`) excuses one
 * curated key.
 */
export const RULES = [
  {
    id: "place",
    pattern: /\bplaces?\b/i,
    use: "Location",
    // "decimal places", "a place inside someone else's", "the only place a
    // line can be re-parented" are the idiom, not the container.
    exempt: [
      /\bdecimal places?\b/gi,
      /\{\{places\}\}/g,
      /\bplace inside\b/gi,
      /\bonly place\b/gi,
    ],
  },
  {
    id: "warehouse",
    pattern: /\bwarehouses?\b/i,
    use: "Location",
    // A job title is a person's, not a place's; "warehouse documents" is the
    // name of a document family (the warehouse module); "Equipment &
    // Warehouse" is the name of a workspace mode, the same word the other four
    // languages use for it. "Warehouse" alone is the name of the documents
    // module (modules.warehouse.name and its launcher title) and of its group
    // on a location's settings tab — a name, not a place.
    exempt: [
      /\bwarehouse operators?\b/gi,
      /\bwarehouse documents?\b/gi,
      /\bequipment & warehouse\b/gi,
    ],
    skipKeys: [
      /modules\/warehouse\/i18n\/en\.json::launcher\.title$/,
      /locales\/en\/modules\.json::modules\.warehouse\.name$/,
    ],
  },
  {
    id: "storage",
    pattern: /\bstorages?\b/i,
    use: "Location",
    // A disk is measured in "Storage (GB)", food keeps in "cold storage", and a
    // starter name such as "IT Storage" is data the user may type — none of
    // them names the place stock is kept in.
    exempt: [
      /\bstorage \(gb\)/gi,
      /\bcold storage\b/gi,
      /\bit storage\b/gi,
      /\bstorage time\b/gi,
    ],
  },
  {
    id: "zone-room-spot",
    pattern: /\b(?:zones?|rooms?|spots?)\b/i,
    use: "Location",
  },
  {
    id: "spoken-for",
    pattern: /\b(?:spoken for|promised|committed)\b/i,
    use: "Reserved",
    exempt: [],
  },
  {
    id: "take-off-stock",
    pattern: /\btak(?:e|es|en|ing) (?:\w+ )?off\b|\bdeduct\w*/i,
    use: "Remove (from stock)",
    exempt: [],
  },
  {
    id: "consume-verb",
    pattern: /\bconsum(?:e|es|ing)\b/i,
    use: "Remove (from stock); Consumed stays the reason and the status",
    exempt: [],
    // A production run consumes its ingredients: a different act with its
    // own ledger line, named in the table.
    skipFiles: [/\/modules\/maker\//],
  },
  {
    id: "product-item",
    pattern: /\b(?:items?|articles?)\b/i,
    use: "Product (the thing that is stocked)",
    // An entry of a list, a menu or a document is not the stocked thing, and
    // "item" is the identifier of a code path the user never reads.
    exempt: [
      /\b(?:line|list|menu|action|checklist|shopping list|cart|document|invoice)\s+items?\b/gi,
      /\bitems? (?:list|lines?|rows?|count|number)\b/gi,
      /\bhelp articles?\b/gi,
    ],
  },
  {
    id: "record-entry",
    pattern: /\bstock (?:entr(?:y|ies)|rows?)\b|\bproduct (?:entr(?:y|ies)|rows?)\b/i,
    use: "Record (a product's stock row in a location)",
    exempt: [],
  },
  {
    id: "held",
    pattern:
      /\b(?:quantity|quantities|stock|amount|units?)\s+(?:is |are |was )?held\b|\bheld (?:for|back|aside)\b/i,
    use: "Reserved",
    exempt: [],
  },
  {
    id: "relocate-shift",
    pattern:
      /\brelocat(?:e|es|ed|ing|ion)\b|\bshift(?:s|ed|ing)? (?:the |this |these |those )?(?:products?|stock|records?|it|them|quantity)\b/i,
    use: "Move",
    exempt: [],
  },
  {
    id: "transfer-verb",
    pattern:
      /\btransfer(?:s|red|ring)? (?:the |this |these |those |some |all )?(?:products?|stock|records?|quantity|it|them)\b/i,
    use: "Move; Transfer stays the name of the internal-transfer document",
    exempt: [],
  },
  {
    id: "transaction",
    pattern: /\btransactions?\b/i,
    use: "Movement (a line of the stock register)",
    exempt: [],
  },
  {
    id: "on-hand",
    pattern: /\bin hand\b|\bcurrent stock\b/i,
    use: "On hand",
    exempt: [],
  },
  {
    id: "used-up",
    pattern: /\bused up\b|\bspent\b/i,
    use: "Consumed (the reason and the status)",
    // Money is spent, stock is not: "total spent" and "spent on" are
    // spending, and the cost-analysis column is the one curated key.
    exempt: [
      /\b(?:total|amount|money) spent\b/gi,
      /\bspent (?:on|in|per)\b/gi,
    ],
    skipKeys: [/modules\/stats\/i18n\/en\.json::costAnalysis\.spent$/],
  },
  {
    id: "shelf",
    pattern: /\bshel(?:f|ves)\b/i,
    use: "Location",
    // Shelf life and shelf-stable describe a product, not a place; "Shelf A"
    // and "Top Shelf" are names a user gives a location, and a bare "Shelf"
    // is the type offered for one.
    exempt: [
      /\bshelf[- ](?:life|stable)\b/gi,
      /\bshelf [A-Z0-9]\b/g,
      /\b(?:top|bottom|upper|lower|middle) shelf\b/gi,
      /^shelf$/gi,
    ],
  },
  {
    id: "profile",
    pattern: /\bprofiles?\b/i,
    use: "Workspace mode (the product profile); a user or document profile keeps its word",
    // A user's own profile and the warehouse module's document profiles are
    // different records that really are profiles (table: "workspace mode").
    exempt: [/\b(?:my|your|user|account|document) profiles?\b/gi],
    skipFiles: [/\/modules\/warehouse\//],
  },
  {
    id: "available-column",
    pattern: /^(?:free|spare|left)$|\b(?:free|spare) (?:stock|quantity|qty)\b/i,
    use: "Available",
    exempt: [],
  },
];

/** Every string leaf of a parsed catalog as `{ path, value }`. */
export function strings(node, path = "") {
  if (typeof node === "string") return [{ path, value: node }];
  if (Array.isArray(node)) {
    return node.flatMap((v, i) => strings(v, `${path}[${i}]`));
  }
  if (node && typeof node === "object") {
    return Object.entries(node).flatMap(([k, v]) =>
      strings(v, path ? `${path}.${k}` : k),
    );
  }
  return [];
}

/**
 * Strings that are names a user might type rather than prose: the starter
 * names offered for a new storage ("Living room", "Zone A") and placeholders
 * that show an example ("e.g. LOC-001, WAREHOUSE-A-1").
 */
const DATA_KEYS = [/^suggestions\./];
const EXAMPLE = /^e\.g\./i;

/** The ids of the rules a string breaks, given where it lives. */
export function rulesBroken(file, path, value, rules = RULES) {
  const broken = [];
  if (EXAMPLE.test(value) || DATA_KEYS.some((re) => re.test(path)))
    return broken;
  for (const rule of rules) {
    if (rule.skipFiles?.some((re) => re.test(file))) continue;
    if (rule.skipKeys?.some((re) => re.test(`${file}::${path}`))) continue;
    const text = (rule.exempt ?? []).reduce(
      (s, re) => s.replace(re, " "),
      value,
    );
    if (rule.pattern.test(text)) broken.push(rule.id);
  }
  return broken;
}

/** Findings of one parsed catalog, keyed `file::path::rule`. */
export function findingsOf(file, catalog, rules = RULES) {
  const found = {};
  for (const { path, value } of strings(catalog)) {
    for (const id of rulesBroken(file, path, value, rules)) {
      found[`${file}::${path}::${id}`] = value;
    }
  }
  return found;
}

/**
 * What the baseline does not already shield: a key it never saw, or a key
 * whose text is no longer the text it shielded.
 */
export function diffBaseline(findings, baseline) {
  const added = [];
  const changed = [];
  for (const [key, value] of Object.entries(findings)) {
    if (!(key in baseline)) added.push(key);
    else if (baseline[key] !== value) changed.push(key);
  }
  const fixed = Object.keys(baseline).filter((key) => !(key in findings));
  return { added, changed, fixed };
}

function catalogFiles() {
  const out = [];
  const locales = join(SRC, "i18n/locales/en");
  for (const entry of readdirSync(locales)) {
    if (entry.endsWith(".json")) out.push(join(locales, entry));
  }
  const modules = join(SRC, "modules");
  for (const entry of readdirSync(modules, { withFileTypes: true })) {
    const file = join(modules, entry.name, "i18n/en.json");
    if (entry.isDirectory() && existsSync(file)) out.push(file);
  }
  return out.sort();
}

export function collectFindings(files = catalogFiles(), rules = RULES) {
  const found = {};
  for (const file of files) {
    const rel = relative(ROOT, file);
    Object.assign(
      found,
      findingsOf(rel, JSON.parse(readFileSync(file, "utf8")), rules),
    );
  }
  return found;
}

function runCli() {
  const args = process.argv.slice(2);
  const quiet = args.includes("--quiet");
  const findings = collectFindings();

  if (args.includes("--write-baseline")) {
    const sorted = Object.fromEntries(Object.entries(findings).sort());
    writeFileSync(BASELINE_PATH, JSON.stringify(sorted, null, 2) + "\n");
    console.log(
      `vocabulary baseline written: ${Object.keys(sorted).length} string(s) → scripts/vocabulary-baseline.json`,
    );
    return;
  }

  const baseline = args.includes("--baseline")
    ? JSON.parse(readFileSync(BASELINE_PATH, "utf8"))
    : {};
  const { added, changed, fixed } = diffBaseline(findings, baseline);
  const failing = [...added, ...changed];

  if (failing.length > 0) {
    if (!quiet) {
      const use = Object.fromEntries(RULES.map((r) => [r.id, r.use]));
      console.error(
        `check-vocabulary: ${failing.length} English string(s) use a retired word (docs/MODULE_NAMES.md, "Domain vocabulary"):`,
      );
      for (const key of failing) {
        const [file, path, id] = key.split("::");
        console.error(
          `  ${file} ${path}  [${id} → ${use[id]}]\n    "${findings[key].slice(0, 110)}"`,
        );
      }
    }
    process.exit(1);
  }

  if (!quiet) {
    console.log(
      `check-vocabulary: OK — ${Object.keys(findings).length} string(s) still use a retired word (all in the baseline).`,
    );
    if (fixed.length > 0) {
      console.log(
        `✓ ${fixed.length} baseline entr(y/ies) fixed — run --write-baseline to refresh.`,
      );
    }
  }
}

// The scan and the exit belong to the CLI run only; under vitest
// `import.meta.url` carries a `/@fs/` prefix, so the comparison is false on
// import and the rules can be loaded without running the gate.
if (import.meta.url === pathToFileURL(process.argv[1] ?? "").href) {
  runCli();
}
