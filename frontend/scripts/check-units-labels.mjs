#!/usr/bin/env node
/**
 * check-units-labels.mjs
 *
 * The backend composes whole refusal sentences of its own (a 400 body, a
 * toast the server sends), so the unit labels are mirrored word for word in
 * ``backend/app/i18n/_units.py`` from the frontend's ``units.*`` block —
 * and a mirror without a guard drifts in silence: one word changed on one
 * side and every language's sentence disagrees with the screen the reader
 * just came from. This is the guard: it reads BOTH sources and demands the
 * backend's symbol set match the frontend's word for word, per language.
 *
 * The frontend's ``units.validation.*`` block is deliberately not mirrored
 * (the server answers those conditions from the error catalogue); symbols
 * the backend does not carry are none of this gate's business.
 *
 * WHICH CATALOGUE IS CANONICAL. ``common:units.<symbol>`` is, and the word
 * for a unit lives nowhere else. There used to be three: this one, keyed by
 * symbol; ``items:uomSymbols.<name>``, keyed by the unit's name; and a copy
 * of eleven entries inside the warehouse module. Two of them had already
 * drifted — a metric cup was "kubek" in one and "filiżanka" in the other —
 * and nothing would have said so, because only this one is mirrored in the
 * backend and guarded here. The symbol wins because it is what the backend
 * composes its refusals from ("Jednostka szt. przyjmuje tylko liczby
 * całkowite"), and a reader must not meet two words for one unit in two
 * sentences of the same screen. ``items:uomNames.<name>`` stays: it
 * translates the unit's *name* ("Piece" → "Sztuka"), which is a different
 * thing from its symbol.
 *
 * So this gate now answers three questions, not one:
 *   1. does the backend's mirror match the screen, word for word;
 *   2. is there a second catalogue of unit words anywhere in the locales;
 *   3. does any sentence put a full stop straight after a unit — because
 *      the Polish symbol for a piece is "szt." and it carries its own, so
 *      "Plan 3 szt.." was on the execution panel of every document.
 * The renderer's side of (2) — a screen printing the raw symbol instead of
 * asking the catalogue — is the `unit-symbol-unresolved` detector's.
 *
 * Modes:
 *   node check-units-labels.mjs           # report and exit 1 on findings
 *   node check-units-labels.mjs --quiet   # exit code only
 */
import { readFileSync, readdirSync, existsSync } from "node:fs";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = resolve(new URL("..", import.meta.url).pathname); // frontend/
const BACKEND_UNITS = resolve(ROOT, "../backend/app/i18n/_units.py");
const LOCALES = resolve(ROOT, "src/i18n/locales");
const LANGUAGES = ["en", "pl", "de", "es", "fr"];

/** `{'sym': 'label', ...}` pairs of one language block in _units.py. */
export function parseBackendBlock(text, language) {
  const block = text.match(new RegExp(`'${language}':\\s*\\{([^}]*)\\}`, "s"));
  if (!block) return null;
  const labels = {};
  const pair = /'((?:[^'\\]|\\.)*)'\s*:\s*'((?:[^'\\]|\\.)*)'/g;
  for (const m of block[1].matchAll(pair)) {
    labels[m[1]] = m[2];
  }
  return labels;
}

/** The backend literal's language blocks, for the missing-language check. */
export function backendLanguages(text) {
  return [...text.matchAll(/^\s{4}'(\w{2})':\s*\{/gm)].map((m) => m[1]);
}

function compare(language, backend, frontend) {
  const findings = [];
  for (const [symbol, label] of Object.entries(backend)) {
    const theirs = frontend[symbol];
    if (theirs === undefined) {
      findings.push(
        `${language}: '${symbol}' missing from the frontend's units block`,
      );
    } else if (theirs !== label) {
      findings.push(
        `${language}: '${symbol}' is '${label}' in the backend mirror but '${theirs}' on the screen`,
      );
    }
  }
  return findings;
}

/** Every locale file of the app, core and modules alike. */
function localeFiles() {
  const files = [];
  const walk = (dir) => {
    for (const entry of readdirSync(dir, { withFileTypes: true })) {
      const full = resolve(dir, entry.name);
      if (entry.isDirectory()) walk(full);
      else if (entry.name.endsWith(".json")) files.push(full);
    }
  };
  walk(LOCALES);
  const modules = resolve(ROOT, "src/modules");
  for (const entry of readdirSync(modules, { withFileTypes: true })) {
    const i18n = resolve(modules, entry.name, "i18n");
    if (entry.isDirectory() && existsSync(i18n)) walk(i18n);
  }
  return files;
}

/** A second catalogue of unit words is a second answer waiting to differ. */
export function rivalCatalogues(files, read = (f) => readFileSync(f, "utf8")) {
  const found = [];
  for (const file of files) {
    const isCommon = file.endsWith(`/common.json`);
    let data;
    try {
      data = JSON.parse(read(file));
    } catch {
      continue;
    }
    if (data.uomSymbols) found.push(`${file}: uomSymbols`);
    if (!isCommon && data.units && typeof data.units === "object") {
      found.push(`${file}: units`);
    }
  }
  return found;
}

/** A sentence that punctuates straight after a unit: "Plan 3 szt..". */
export function punctuationAfterUnit(
  files,
  read = (f) => readFileSync(f, "utf8"),
) {
  const found = [];
  const offends = /\{\{(?:unit|uom)\}\}\s*[.,;]/;
  for (const file of files) {
    let data;
    try {
      data = JSON.parse(read(file));
    } catch {
      continue;
    }
    const walk = (node, path) => {
      if (node && typeof node === "object") {
        for (const [key, value] of Object.entries(node)) {
          walk(value, path ? `${path}.${key}` : key);
        }
      } else if (typeof node === "string" && offends.test(node)) {
        found.push(`${file}: ${path}`);
      }
    };
    walk(data, "");
  }
  return found;
}

/**
 * The gate itself. Guarded, because the file also exports its readers: a
 * test that imports them used to run the whole gate on import — against a
 * path that does not exist under the test runner — and exit the process.
 */
function main() {
  const quiet = process.argv.includes("--quiet");
  const findings = [];

  if (!existsSync(BACKEND_UNITS)) {
    console.error(`✗ backend mirror not found: ${BACKEND_UNITS}`);
    process.exit(1);
  }

  const backendText = readFileSync(BACKEND_UNITS, "utf8");
  const backendLangs = backendLanguages(backendText);
  for (const language of LANGUAGES) {
    const backend = parseBackendBlock(backendText, language);
    if (backend === null) {
      findings.push(`backend mirror has no '${language}' block`);
      continue;
    }
    if (!backendLangs.includes(language)) {
      findings.push(`backend mirror does not declare '${language}'`);
    }
    const commonPath = resolve(LOCALES, language, "common.json");
    if (!existsSync(commonPath)) {
      findings.push(`${language}: frontend locale not found: ${commonPath}`);
      continue;
    }
    const frontend = JSON.parse(readFileSync(commonPath, "utf8")).units ?? {};
    findings.push(...compare(language, backend, frontend));
  }

  const locales = localeFiles();
  for (const rival of rivalCatalogues(locales)) {
    findings.push(
      `${rival}: a second catalogue of unit words — the word lives in common:units.<symbol>`,
    );
  }
  for (const sentence of punctuationAfterUnit(locales)) {
    findings.push(
      `${sentence}: punctuation straight after the unit — "szt." carries its own full stop`,
    );
  }

  if (findings.length > 0) {
    if (!quiet) {
      console.error(
        `✗ the unit-label mirror drifted from the screen (${findings.length}):`,
      );
      for (const f of findings) console.error(`  - ${f}`);
      console.error(
        "  fix _units.py or the locale's units block — both, word for word.",
      );
    }
    process.exit(1);
  }
  if (!quiet) {
    console.log("✓ unit-label mirror matches the screen word for word");
  }
}

if (process.argv[1] && fileURLToPath(import.meta.url) === process.argv[1]) {
  main();
}
