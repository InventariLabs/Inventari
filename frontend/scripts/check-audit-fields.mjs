#!/usr/bin/env node
/**
 * check-audit-fields.mjs
 *
 * Every field name the backend writes into an audit snapshot has to be a name
 * the journal can say in the reader's language. Nothing compared the two sets,
 * so a new field entered the journal in English and nobody found out — which
 * is how forty of the fifty-three keys in the organisation journal were
 * English in a Polish interface, `barcode` and `old_quantity` first among
 * them.
 *
 * The two halves of the gate:
 *
 *   backend/scripts/export_audit_snapshot_keys.py
 *     reads the writers that declare their keys and writes them to
 *     `scripts/audit-snapshot-keys.json` (refresh: `make sync-audit-fields`)
 *
 *   this file
 *     compares that set with `settings.audit.fields` in all five catalogs.
 *
 * Modes:
 *   node check-audit-fields.mjs                  # exit 1 on any gap
 *   node check-audit-fields.mjs --baseline       # only NEW gaps fail
 *   node check-audit-fields.mjs --write-baseline # record the current gaps
 *   AUDIT_KEYS_FRESH=<path> node check-audit-fields.mjs --freshness
 *                                                # the saved artefact has to be
 *                                                # the one the backend exports now
 *
 * The same artefact carries the values of the backend's `AuditTargetType`, and
 * the same catalogues have to name each of them under
 * `settings.audit.targetTypes`: the journal's filter and its Target column
 * print a type the catalogue does not know as the raw identifier.
 *
 * Freshness is the caller's half of the gate: this script cannot regenerate the
 * artefact (the writers are Python, and this runs where the frontend does), so
 * `make check-audit-fields-fresh` exports the keys to a file and hands the path
 * over in AUDIT_KEYS_FRESH. The comparison runs first and the label check
 * follows it, so one command answers both questions.
 *
 * Baseline file: scripts/audit-fields-baseline.json
 * The goal is an EMPTY baseline — add the translation, don't grandfather it.
 */
import { existsSync, readFileSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";
import { pathToFileURL } from "node:url";

// `import.meta.dirname`, not `new URL("..", import.meta.url)`: under vitest
// vite rewrites that expression as an asset URL, and its path is not this
// directory's parent.
const ROOT = resolve(import.meta.dirname, ".."); // frontend/
const KEYS_PATH = resolve(
  ROOT,
  process.env.AUDIT_KEYS ?? "scripts/audit-snapshot-keys.json",
);
const BASELINE_PATH = resolve(
  ROOT,
  process.env.AUDIT_FIELDS_BASELINE ?? "scripts/audit-fields-baseline.json",
);
const LANGUAGES = ["en", "pl", "de", "fr", "es"];
/** Where `auditFieldLabel` looks a segment up — see utils/auditChanges.ts.
 *
 * `AUDIT_LOCALES_DIR` hands the gate another set of catalogues (same shape,
 * `<language>/common.json`): the test of the gate itself removes one key and
 * watches the gate fall, which is the only proof it has teeth.
 */
const LOCALES_DIR = process.env.AUDIT_LOCALES_DIR
  ? resolve(process.env.AUDIT_LOCALES_DIR)
  : resolve(ROOT, "src/i18n/locales");
/** Where `auditFieldLabel` looks a segment up — see utils/auditChanges.ts. */
const CATALOG_POINTER = "/settings/audit/fields/";

/** The two vocabularies the artefact is read against, and where they live. */
const FIELDS = "fields";
const TARGET_TYPES = "targetTypes";

export function catalogKeys(languages = LANGUAGES, section = FIELDS) {
  const perLanguage = new Map();
  for (const language of languages) {
    const file = resolve(LOCALES_DIR, `${language}/common.json`);
    const json = JSON.parse(readFileSync(file, "utf8"));
    perLanguage.set(
      language,
      new Set(Object.keys(json.settings.audit[section])),
    );
  }
  return perLanguage;
}

/**
 * Keys the backend declares that a catalogue does not name.
 *
 * Every language counts separately on purpose: a key translated into English
 * and Polish but not into German is still a German reader meeting a raw
 * identifier, and reporting it against `en` alone would call the tree clean.
 */
export function gaps(keys, perLanguage = catalogKeys()) {
  const found = [];
  for (const language of perLanguage.keys()) {
    const known = perLanguage.get(language);
    for (const key of keys) {
      if (!known.has(key)) found.push({ language, key });
    }
  }
  return found;
}

function loadKeys() {
  if (!existsSync(KEYS_PATH)) {
    console.error(
      `check-audit-fields: ${KEYS_PATH} is missing — run \`make sync-audit-fields\` first.`,
    );
    process.exit(2);
  }
  const json = JSON.parse(readFileSync(KEYS_PATH, "utf8"));
  return {
    keys: json.keys ?? [],
    targetTypes: json["target-types"] ?? [],
    declarationsRead: json["declarations-read"] ?? 0,
    uncovered: json["uncovered-writer-files"] ?? [],
  };
}

/**
 * What a freshly exported artefact holds that the saved one does not, and the
 * other way round.
 *
 * The saved artefact is what the label half reads, so an artefact left behind
 * by the writers is a gate reading a tree that no longer exists. That is not a
 * hypothetical: `enabled_modules` reached the journal's snapshots, the saved
 * file went on holding its 122 keys, and the gate called the journal clean
 * while a reader was looking at the raw field name on screen. Nothing
 * regenerated the file, and nothing said it was old.
 */
export function staleKeys(saved, fresh) {
  const savedSet = new Set(saved);
  const freshSet = new Set(fresh);
  return {
    missing: fresh.filter((key) => !savedSet.has(key)),
    extra: saved.filter((key) => !freshSet.has(key)),
  };
}

function loadBaseline() {
  if (!existsSync(BASELINE_PATH)) return [];
  const json = JSON.parse(readFileSync(BASELINE_PATH, "utf8"));
  return json.gaps ?? [];
}

/** A gap in the fields catalogue has no `section`; it is the original kind. */
function baseKey(entry) {
  return `${entry.section ?? FIELDS}:${entry.language}:${entry.key}`;
}

/** Every gap of both kinds, the target-type ones tagged with their section. */
function allGaps(keys, targetTypes) {
  return [
    ...gaps(keys),
    ...gaps(targetTypes, catalogKeys(LANGUAGES, TARGET_TYPES)).map((gap) => ({
      ...gap,
      section: TARGET_TYPES,
    })),
  ];
}

/**
 * The saved artefact against the one the backend has just exported.
 *
 * *freshPath* comes in through AUDIT_KEYS_FRESH because the two run in
 * different places: `make check-audit-fields-fresh` asks the backend container
 * for the keys and writes them to a temporary file, then calls this script with
 * the path. Same shape as the API-type freshness check, for the same reason —
 * the generator lives on the other side of the tree from the gate.
 */
function checkFreshness(
  savedKeys,
  savedTargetTypes,
  savedDeclarations,
  savedUncovered,
  quiet,
) {
  const freshPath = process.env.AUDIT_KEYS_FRESH;
  if (!freshPath) {
    console.error(
      "check-audit-fields --freshness: AUDIT_KEYS_FRESH is not set — the keys have to be exported first (`make check-audit-fields-fresh` does both steps).",
    );
    process.exit(2);
  }
  if (!existsSync(freshPath)) {
    console.error(
      `check-audit-fields --freshness: ${freshPath} is not there — the export step did not write it.`,
    );
    process.exit(2);
  }
  const fresh = JSON.parse(readFileSync(resolve(freshPath), "utf8"));
  const freshKeys = fresh.keys ?? [];
  const { missing, extra } = staleKeys(savedKeys, freshKeys);

  if (missing.length > 0 || extra.length > 0) {
    console.error(
      `check-audit-fields: ${KEYS_PATH} is not what the backend declares today — ${savedKeys.length} saved, ${freshKeys.length} declared by ${fresh["declarations-read"] ?? 0} declaration(s):`,
    );
    for (const key of missing) console.error(`  missing: ${key}`);
    for (const key of extra) console.error(`  no longer declared: ${key}`);
    console.error(
      "Run `make sync-audit-fields`. The gate reads this file, so a stale one makes it green over a journal it cannot see.",
    );
    process.exit(1);
  }

  // The target types are the other half of what the artefact stands for: a
  // new enum member the saved file does not hold is a type the label check
  // below never asks the catalogues about.
  const freshTargetTypes = fresh["target-types"] ?? [];
  const staleTypes = staleKeys(savedTargetTypes, freshTargetTypes);
  if (staleTypes.missing.length > 0 || staleTypes.extra.length > 0) {
    console.error(
      `check-audit-fields: the target types in ${KEYS_PATH} are not what the backend declares today:`,
    );
    for (const type of staleTypes.missing) console.error(`  missing: ${type}`);
    for (const type of staleTypes.extra)
      console.error(`  no longer declared: ${type}`);
    console.error("Run `make sync-audit-fields`.");
    process.exit(1);
  }

  // Keys can stand still while a writer goes unread — a renamed declaration
  // (or a duplicate pair elsewhere) keeps every key in the artefact at the
  // moment the writer's own universe drops out of it. That is how a renamed
  // `AUDIT_PAYLOAD_SCHEMA` once passed this half of the gate: 3 declarations
  // where 4 had been, 130 keys either way, green.
  const freshDeclarations = fresh["declarations-read"] ?? 0;
  if (savedDeclarations !== freshDeclarations) {
    console.error(
      `check-audit-fields: declarations-read moved — saved ${savedDeclarations}, the backend declares ${freshDeclarations} today.`,
    );
    console.error(
      "A writer lost its declaration (or a new one appeared). Run `make sync-audit-fields` and read the artefact's diff before trusting green.",
    );
    process.exit(1);
  }
  const freshUncovered = fresh["uncovered-writer-files"] ?? [];
  const uncoveredDrift = [
    ...savedUncovered
      .filter((file) => !freshUncovered.includes(file))
      .map((file) => `  no longer uncovered: ${file}`),
    ...freshUncovered
      .filter((file) => !savedUncovered.includes(file))
      .map((file) => `  newly uncovered: ${file}`),
  ];
  if (uncoveredDrift.length > 0) {
    console.error(
      "check-audit-fields: uncovered-writer-files is not what the backend reports today —",
    );
    for (const line of uncoveredDrift) console.error(line);
    console.error(
      "A funnel writer lost its declaration (or found one). Run `make sync-audit-fields`.",
    );
    process.exit(1);
  }

  if (!quiet) {
    console.log(
      `check-audit-fields: the saved artefact matches the ${freshKeys.length} key(s) the backend declares today` +
        `, its ${freshDeclarations} declaration(s) and ${freshUncovered.length} uncovered writer(s)`,
    );
  }
}

function runCli() {
  const quiet = process.argv.includes("--quiet");
  const writeBaseline = process.argv.includes("--write-baseline");
  const onlyNew = process.argv.includes("--baseline");
  const freshness = process.argv.includes("--freshness");

  const { keys, targetTypes, declarationsRead, uncovered } = loadKeys();

  if (freshness) {
    checkFreshness(keys, targetTypes, declarationsRead, uncovered, quiet);
  }

  // Structural, never grand fathered: the baseline exists for translation
  // debt, and an unread writer is not debt — it is the gate's own subject.
  // The artefact names the funnel writers whose dynamic `keys=` no
  // declaration covers; until the writer declares the pair it draws from,
  // the journal can print raw field names this gate cannot see.
  if (uncovered.length > 0) {
    console.error(
      `check-audit-fields: ${uncovered.length} journal_config_change writer(s) cut their snapshot keys from a payload with no declaration the artefact could read:`,
    );
    for (const file of uncovered) console.error(`  ${file}`);
    console.error(
      "Declare `AUDIT_PAYLOAD_SCHEMA = ('UpdateSchema', 'Model')` beside the writer — the journal prints the raw keys until the artefact can read it.",
    );
    process.exit(1);
  }

  const found = allGaps(keys, targetTypes);
  const baseline = loadBaseline();
  const baselineSet = new Set(baseline.map(baseKey));
  const reported = onlyNew
    ? found.filter((gap) => !baselineSet.has(baseKey(gap)))
    : found;

  if (writeBaseline) {
    writeFileSync(
      BASELINE_PATH,
      JSON.stringify(
        {
          generatedBy: "node scripts/check-audit-fields.mjs --write-baseline",
          note: "Snapshot field names and target types with no translation yet. The goal is an empty file.",
          gaps: found,
        },
        null,
        2,
      ) + "\n",
    );
    console.log(
      `check-audit-fields: baseline written with ${found.length} gap(s) of ${keys.length} key(s) and ${targetTypes.length} target type(s) × ${LANGUAGES.length} language(s)`,
    );
    process.exit(0);
  }

  const summary = `check-audit-fields: ${keys.length} declared key(s) from ${declarationsRead} declaration(s) and ${targetTypes.length} target type(s), read against ${LANGUAGES.length} catalogues`;

  if (reported.length > 0) {
    if (!quiet) {
      console.error(
        `${summary} — ${reported.length} name(s) no catalogue knows:`,
      );
      for (const gap of reported)
        console.error(
          `  ${gap.language}: ${gap.key}${gap.section ? ` (${gap.section})` : ""}`,
        );
      const first = reported[0];
      console.error(
        `Add \`settings.audit.${first.section ?? FIELDS}.${first.key}\` to src/i18n/locales/<lang>/common.json — the journal prints the raw key until you do.`,
      );
    }
    process.exit(1);
  }

  if (!quiet) {
    console.log(
      onlyNew
        ? `${summary} — ✓ no gap beyond the baseline (${baseline.length} recorded)`
        : `${summary} — ✓ every declared name is in every catalogue`,
    );
  }
}

if (import.meta.url === pathToFileURL(process.argv[1] ?? "").href) {
  runCli();
}
