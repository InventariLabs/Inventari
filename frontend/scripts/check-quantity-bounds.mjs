#!/usr/bin/env node
/**
 * check-quantity-bounds.mjs
 *
 * The store's quantity contract lives once, in
 * ``backend/app/schemas/validators.py``: ``QUANTITY_MAX_DIGITS`` and
 * ``QUANTITY_SCALE`` shape the numeric column, the schemas take their
 * ``le=`` from the derived ceiling, and the add-to-list form mirrors the
 * ceiling and the step. Python cannot be imported into the bundle, so the
 * frontend keeps its own two numbers — and nothing used to compare the two
 * sides: a constant changed in Python passed every gate while the form and
 * the five translations went on repeating the old one.
 *
 * This is the guard. It reads BOTH sides and answers three questions:
 *   1. does ``QUANTITY_MAX`` in quantityBounds.ts equal the backend's max;
 *   2. does ``QUANTITY_STEP`` in useUomPrecision.ts equal the backend's step;
 *   3. does every shopping-list catalogue's ``addItem.validation.quantityMax``
 *      interpolate ``{{max}}`` rather than paste the number into the sentence;
 *   4. does every backend catalogue's "rounds to zero" refusal interpolate
 *      ``{smallest}`` rather than paste the step ("0.001") into the sentence.
 *
 * Modes:
 *   node check-quantity-bounds.mjs           # report and exit 1 on findings
 *   node check-quantity-bounds.mjs --quiet   # exit code only
 */
import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = resolve(new URL("..", import.meta.url).pathname); // frontend/
const BACKEND_VALIDATORS = resolve(
  ROOT,
  "../backend/app/schemas/validators.py",
);
const FRONTEND_MAX = resolve(
  ROOT,
  "src/modules/shopping_lists/quantityBounds.ts",
);
const FRONTEND_STEP = resolve(ROOT, "src/hooks/useUomPrecision.ts");
const CATALOGS = ["en", "pl", "de", "es", "fr"].map((lang) =>
  resolve(ROOT, `src/modules/shopping_lists/i18n/${lang}.json`),
);
// The backend's refusals live in Python catalogues (en and pl share a file).
const ERROR_CATALOGS = ["en_pl", "de", "es", "fr", "pt"].map((lang) =>
  resolve(ROOT, `../backend/app/i18n/_errors_${lang}.py`),
);
const ZERO_REFUSAL_KEY = "shopping_list_item_quantity_rounds_to_zero";

/** The digits and scale the backend declares, or null when it lost them. */
export function parseBackendQuantity(text) {
  const digits = text.match(/^QUANTITY_MAX_DIGITS\s*=\s*(\d+)\s*$/m);
  const scale = text.match(/^QUANTITY_SCALE\s*=\s*(\d+)\s*$/m);
  if (!digits || !scale) return null;
  return { maxDigits: Number(digits[1]), scale: Number(scale[1]) };
}

/** The ceiling and step the declared shape derives — the backend's formulas. */
export function expectedBounds({ maxDigits, scale }) {
  const whole = "9".repeat(maxDigits - scale);
  const fraction = "9".repeat(scale);
  return {
    max: Number(`${whole}.${fraction}`),
    step: Number(`0.${"0".repeat(scale - 1)}1`),
  };
}

/** The number an ``export const NAME = 999_999_999.999;`` line holds. */
export function parseTsConstant(text, name) {
  const match = text.match(
    new RegExp(`export const ${name}\\s*=\\s*([0-9_]+(?:\\.[0-9_]+)?)\\s*;`),
  );
  return match ? Number(match[1].replaceAll("_", "")) : null;
}

function sameNumber(one, other) {
  return Math.abs(one - other) < 1e-9;
}

/** The ceiling the frontend mirrors against the one the backend derives. */
export function boundsFindings(backend, frontendMax, frontendStep) {
  const expected = expectedBounds(backend);
  const findings = [];
  if (frontendMax === null) {
    findings.push(`${FRONTEND_MAX}: no exported QUANTITY_MAX`);
  } else if (!sameNumber(frontendMax, expected.max)) {
    findings.push(
      `${FRONTEND_MAX}: QUANTITY_MAX is ${frontendMax} but the backend column holds ${expected.max} ` +
        `(numeric(${backend.maxDigits}, ${backend.scale}))`,
    );
  }
  if (frontendStep === null) {
    findings.push(`${FRONTEND_STEP}: no exported QUANTITY_STEP`);
  } else if (!sameNumber(frontendStep, expected.step)) {
    findings.push(
      `${FRONTEND_STEP}: QUANTITY_STEP is ${frontendStep} but the backend stores ${expected.step} ` +
        `(numeric(${backend.maxDigits}, ${backend.scale}))`,
    );
  }
  return findings;
}

/**
 * A sentence that repeats the ceiling is a copy waiting to lie. The value
 * has to arrive through the interpolation, from the constant the gate above
 * holds to the backend.
 */
export function ceilingSentenceFindings(catalogs) {
  const findings = [];
  for (const { path, text } of catalogs) {
    let value;
    try {
      value = JSON.parse(text).addItem?.validation?.quantityMax;
    } catch {
      findings.push(`${path}: not readable as JSON`);
      continue;
    }
    if (typeof value !== "string") {
      findings.push(`${path}: addItem.validation.quantityMax is missing`);
      continue;
    }
    if (!value.includes("{{max}}")) {
      findings.push(
        `${path}: addItem.validation.quantityMax does not interpolate {{max}} — it repeats the ceiling: "${value}"`,
      );
    } else if (/\d{4,}/.test(value)) {
      findings.push(
        `${path}: addItem.validation.quantityMax still carries a pasted number beside {{max}}: "${value}"`,
      );
    }
  }
  return findings;
}

/**
 * The refusal for a quantity that rounds to zero names the smallest amount
 * the column keeps. The route fills ``{smallest}`` from the backend's step; a
 * sentence that pastes the number keeps stating it after the scale moves.
 * Every catalogue has to carry the key, and every line holding it has to
 * interpolate.
 */
export function zeroRefusalFindings(catalogs) {
  const findings = [];
  const line = new RegExp(`'${ZERO_REFUSAL_KEY}':\\s*(.+)$`, "gm");
  for (const { path, text } of catalogs) {
    const sentences = [...text.matchAll(line)].map((match) => match[1]);
    if (sentences.length === 0) {
      findings.push(`${path}: no ${ZERO_REFUSAL_KEY} sentence`);
    }
    for (const sentence of sentences) {
      if (!sentence.includes("{smallest}")) {
        findings.push(
          `${path}: ${ZERO_REFUSAL_KEY} does not interpolate {smallest} — it repeats the step: ${sentence}`,
        );
      }
    }
  }
  return findings;
}

/**
 * The gate itself. Guarded, because the file also exports its readers: a
 * test that imports them used to run the whole gate on import.
 */
function main() {
  const quiet = process.argv.includes("--quiet");
  const findings = [];

  if (!existsSync(BACKEND_VALIDATORS)) {
    console.error(`✗ backend source not found: ${BACKEND_VALIDATORS}`);
    process.exit(1);
  }

  const backend = parseBackendQuantity(
    readFileSync(BACKEND_VALIDATORS, "utf8"),
  );
  if (backend === null) {
    findings.push(
      `${BACKEND_VALIDATORS}: QUANTITY_MAX_DIGITS/QUANTITY_SCALE not found`,
    );
  } else {
    findings.push(
      ...boundsFindings(
        backend,
        parseTsConstant(readFileSync(FRONTEND_MAX, "utf8"), "QUANTITY_MAX"),
        parseTsConstant(readFileSync(FRONTEND_STEP, "utf8"), "QUANTITY_STEP"),
      ),
    );
  }

  findings.push(
    ...ceilingSentenceFindings(
      CATALOGS.map((path) => ({ path, text: readFileSync(path, "utf8") })),
    ),
  );

  findings.push(
    ...zeroRefusalFindings(
      ERROR_CATALOGS.map((path) => ({
        path,
        text: readFileSync(path, "utf8"),
      })),
    ),
  );

  if (findings.length > 0) {
    if (!quiet) {
      console.error(
        `✗ the form's quantity bounds drifted from the store (${findings.length}):`,
      );
      for (const finding of findings) console.error(`  - ${finding}`);
      console.error(
        "  fix the frontend mirror or the sentences — the backend's validators.py is the source.",
      );
    }
    process.exit(1);
  }
  if (!quiet) {
    console.log(
      "✓ the form's quantity bounds and ceiling sentences match the store",
    );
  }
}

if (process.argv[1] && fileURLToPath(import.meta.url) === process.argv[1]) {
  main();
}
