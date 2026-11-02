#!/usr/bin/env node
/**
 * check-quantity-render.mjs
 *
 * A unit of measure reaches the screen through a resolver, never as it came
 * off the wire.
 *
 * The symbol stored on a record is the canonical one — "pcs", "g", "pack" —
 * and printing it verbatim puts "4.000 pcs" on a Polish screen beside
 * "14,00 USD", two words and two decimal marks from two different languages
 * in one line. The translation has been in the core catalogue the whole time
 * (`common:units.<symbol>`), and so has the resolver that reads it:
 * `formatQuantityLocalized(t, quantity, symbol, rounding)`. Its own docstring
 * names both halves of the defect — the English symbol, and the three
 * decimals a `numeric(10,3)` column carries onto a unit that does not divide.
 *
 * Guarding the symbol guards the number with it: the resolver takes both, so
 * a call site that adopts it stops printing "4.000" at the same moment it
 * stops printing "pcs". That is why this gate reads the symbol and not the
 * quantity — a quantity identifier appears in comparisons, in `aria-valuenow`
 * and in payloads, and a rule chasing it would cry wolf until nobody read
 * the output.
 *
 * A read passes when a known resolver is in reach of it: one of the shared
 * ones, a `common:units.` lookup, or a wrapper defined in the same file whose
 * own body reaches one of those — because a one-line local helper around
 * `formatQuantityLocalized` is the resolver, and a gate that could not see
 * that would report the tables that already do this right.
 *
 * A read a statement spends on a name — `const unit = line.uom_symbol…` —
 * is followed to the places the name reaches. The statement itself is a
 * decision and not a sentence, but the name can be both: on the stock-take
 * card it fed `t("item.decreaseCountInUnit", { unit, … })` and printed "pcs"
 * inside a Polish sentence while every read the scanner watched sat in a
 * statement it looked away from. A name bound through a resolver
 * (`unitLabel(t, …)`) carries a resolved word and is not followed.
 *
 * What the scanner deliberately does not read:
 *   - a string literal `"uom_symbol"` — a column name in an import mapping is
 *     not a render;
 *   - `uom_symbol:` as an object key — building a payload is not a render;
 *   - a statement body (anything holding a `;`) — `COUNTABLE_UOMS.has(i.uom_symbol)`
 *     is a decision, not a sentence shown to anyone;
 *   - a value handed to a component as a prop (`uomSymbol={unitSymbol}`) — the
 *     consumer either renders it, and is read where it writes that render, or
 *     uses it for something else (precision, a step) and never prints it.
 *
 * Each of those was a false positive in an earlier version of this scanner,
 * and each is pinned by a test. An i18n interpolation value
 * (`t("...", { unit: line.uom_symbol })`) is NOT excluded: that is precisely
 * how "pcs" gets inside a translated sentence.
 *
 * Modes:
 *   node check-quantity-render.mjs                    # report and exit 1
 *   node check-quantity-render.mjs --baseline         # only NEW findings fail
 *   node check-quantity-render.mjs --write-baseline   # snapshot current
 *   node check-quantity-render.mjs --quiet            # exit code only
 *
 * Baseline: frontend/scripts/quantity-render-baseline.json
 * The goal is an empty baseline. An entry is a screen still printing the
 * database's own spelling of a unit.
 */
import { readFileSync, readdirSync, writeFileSync, existsSync } from "node:fs";
import { resolve, relative } from "node:path";
import { fileURLToPath } from "node:url";

import { blankComments } from "./source-text.mjs";

const ROOT = resolve(new URL("..", import.meta.url).pathname); // frontend/
const SRC = resolve(ROOT, "src");
const BASELINE_PATH = resolve(ROOT, "scripts/quantity-render-baseline.json");

/**
 * The shared resolvers. The translation lookup itself lives in
 * `lib/i18nHelpers.ts`, which is the one place allowed to read a symbol
 * without a resolver above it — `wmsUnitLabel` is that module's WMS wrapper
 * around `unitLabel` (one answer for the empty unit), so a symbol handed to
 * it is translated the same way and never reaches the screen as it came off
 * the wire.
 */
export const RESOLVERS = [
  "formatQuantityLocalized",
  "getDocumentUnitLabel",
  "unitLabel",
  "wmsUnitLabel",
];

/**
 * A lookup in a unit catalogue counts as resolving. Two namespaces carry unit
 * words in this tree — `common:units.<symbol>`, the core one the resolvers
 * read, and `items:uomSymbols.<name>`, keyed by the unit's name instead. Both
 * go through i18n, which is this gate's question; that there are two of them
 * is a separate finding and not one a scanner should pretend to settle.
 */
const UNITS_KEY =
  /common:units\.|items:uomSymbols\.|items:uomNames\.|`units\.\$\{|["']units\.["']/;

/** A property read of the symbol — not a key, not a string literal. */
const SYMBOL_READ =
  /(?:\.\s*(?:uom_symbol|unit_symbol)|\buom\.symbol)\b(?!\s*:)/g;

function walk(dir, out = []) {
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const full = resolve(dir, entry.name);
    if (entry.isDirectory()) walk(full, out);
    else out.push(full);
  }
  return out;
}

export function isScanned(rel) {
  if (!/\.tsx?$/.test(rel)) return false;
  if (/\.test\.tsx?$/.test(rel)) return false;
  // The resolver's own home: it reads the symbol to translate it.
  if (rel === "lib/i18nHelpers.ts") return false;
  if (rel === "utils/formatters.ts") return false;
  if (rel === "modules/warehouse/unitLabels.ts") return false;
  return true;
}

/** Comments blanked, not removed, so the line number stays true. */
/**
 * Names defined in this file whose body reaches a resolver.
 *
 * A table wrapping `formatQuantityLocalized` in a two-line `quantity()` helper
 * is doing the right thing; without this the gate would report it and the
 * reader would learn the output is noise.
 */
export function localResolvers(text) {
  const names = new Set();
  const decl = /(?:const|let|var|function)\s+([A-Za-z0-9_$]+)\s*(?:=|\()/g;
  let match;
  while ((match = decl.exec(text)) !== null) {
    const body = text.slice(match.index, match.index + 1500);
    if (RESOLVERS.some((r) => body.includes(r)) || UNITS_KEY.test(body)) {
      names.add(match[1]);
    }
  }
  return names;
}

/** The innermost braces a position sits in, as offsets into `text`. */
export function braceBounds(text, index) {
  let start = index;
  let depth = 0;
  for (let i = index; i >= 0; i--) {
    const char = text[i];
    if (char === "}") depth++;
    else if (char === "{") {
      if (depth === 0) {
        start = i;
        break;
      }
      depth--;
    }
  }
  let end = index;
  depth = 0;
  for (let i = index; i < text.length; i++) {
    const char = text[i];
    if (char === "{") depth++;
    else if (char === "}") {
      if (depth === 0) {
        end = i;
        break;
      }
      depth--;
    }
  }
  return { start, end: end + 1 };
}

/** The braced expression a position sits in. */
export function bracedAround(text, index) {
  const { start, end } = braceBounds(text, index);
  return text.slice(start, end);
}

/**
 * The callees whose parentheses are still open at a position.
 *
 * Read outward, not as a character window. The window this replaced accepted
 * a raw `<span>{line.uom_symbol}</span>` because a resolved call sat on the
 * line above it — the planted violation the gate was measured with went
 * straight through. A call encloses the read or it does not; proximity is not
 * evidence.
 */
export function enclosingCalls(text, index) {
  const calls = [];
  let depth = 0;
  for (let i = index; i >= 0; i--) {
    const char = text[i];
    if (char === ")") depth++;
    else if (char === "(") {
      if (depth > 0) {
        depth--;
        continue;
      }
      const callee = text
        .slice(Math.max(0, i - 80), i)
        .match(/([A-Za-z0-9_$]+)\s*$/);
      // The arguments written before the read: this is where a
      // `common:units.` lookup sits when the symbol is only its fallback.
      calls.push({
        name: callee?.[1] ?? "",
        args: text.slice(i + 1, index),
        at: i,
      });
      if (calls.length >= 4) break;
    }
  }
  return calls;
}

/** A statement is a decision, not a sentence anyone reads. */
export function isStatement(expr) {
  if (expr.includes(";")) return true;
  return /^\{\s*(?:const|let|var|if|return|for|while|function)\b/.test(expr);
}

/** Translators — the calls whose object argument becomes a sentence. */
const TRANSLATORS = new Set(["t", "tDyn", "tDynamic", "translate", "tFor"]);

/**
 * An object being built, not a sentence being shown.
 *
 * `{ uom_symbol: rule.uom_symbol }` handed to a form, or a hint object a
 * hook returns, is a payload: the screen that renders it is read on its own
 * terms, here, like every other. The one object literal that IS a render is
 * the interpolation argument of a translator — `t("…", { unit: symbol })`
 * puts "pcs" inside a translated sentence — so an object inside one of those
 * stays a finding.
 */
export function isPayloadObject(expr, enclosing = []) {
  if (!/^\{\s*(?:[A-Za-z_$][\w$]*|"[^"]+"|'[^']+')\s*:/.test(expr))
    return false;
  return !enclosing.some((call) => TRANSLATORS.has(call.name));
}

/** The line a position is on. */
function lineOf(text, index) {
  return text.slice(0, index).split("\n").length;
}

/**
 * The end of the statement a binding's right-hand side runs to.
 *
 * Braces, brackets and parentheses are counted, and a string or template
 * literal is skipped whole, so the `;` the statement ends on is the one at
 * depth zero and not one inside an arrow body or a message.
 */
function statementEnd(text, from) {
  let depth = 0;
  let quote = "";
  const limit = Math.min(text.length, from + 2000);
  for (let i = from; i < limit; i++) {
    const char = text[i];
    if (quote) {
      if (char === "\\") i++;
      else if (char === quote) quote = "";
      continue;
    }
    if (char === '"' || char === "'" || char === "`") quote = char;
    else if (char === "(" || char === "[" || char === "{") depth++;
    else if (char === ")" || char === "]" || char === "}") {
      if (depth === 0) return i + 1;
      depth--;
    } else if (char === ";" && depth === 0) return i + 1;
  }
  return limit;
}

/**
 * Names a raw symbol read was bound to, with the offset of the binding.
 *
 * `const unit = line.uom_symbol?.trim() || null` spends its read on a
 * statement, and the name then carries "pcs" wherever it goes. A binding
 * whose right-hand side reaches a resolver or a `common:units.` lookup is
 * resolved at the seam and is not one of these.
 *
 * Neither is a name bound to a value *derived* from the read — a predicate
 * (`isFractionalCountable(item.uom_symbol)`), a handler `useCallback` builds.
 * The symbol went into a computation and what came out is a boolean or a
 * function, not the unit; following it would call `className={isCountable}`
 * a sentence about units.
 */
export function rawAliases(text, inScope) {
  const names = new Map();
  const decl = /(?:const|let|var)\s+([A-Za-z0-9_$]+)\s*=\s*/g;
  let match;
  while ((match = decl.exec(text)) !== null) {
    const name = match[1];
    const at = match.index;
    const from = at + match[0].length;
    const to = statementEnd(text, from);
    const rhs = text.slice(from, to);
    if (inScope.some((n) => rhs.includes(`${n}(`)) || UNITS_KEY.test(rhs))
      continue;
    let carries = false;
    let read;
    SYMBOL_READ.lastIndex = from;
    while ((read = SYMBOL_READ.exec(text)) !== null && read.index < to) {
      // A call opened before the right-hand side holds the whole binding as
      // its argument (`memo(function C() { … })`); what makes the value
      // derived is a call written inside the right-hand side, around the read.
      const enclosing = enclosingCalls(text, read.index).filter(
        (call) => call.at >= from,
      );
      if (!enclosing.some((c) => c.name && !inScope.includes(c.name))) {
        carries = true;
        break;
      }
    }
    SYMBOL_READ.lastIndex = 0;
    if (!carries) continue;
    names.set(name, at);
  }
  return names;
}

/**
 * Whether the braces opened at `start` hold a JSX attribute value.
 *
 * `uomSymbol={unitSymbol}` gives the symbol to a component that asked for it
 * — precision, a step — and whether that value is printed is the consumer's
 * render, read where the consumer writes it. An object assigned to a
 * variable reads the same way from here, and is a payload by the same rule.
 */
function isJsxAttributeValue(text, start) {
  let i = start - 1;
  while (i >= 0 && /\s/.test(text[i])) i--;
  if (text[i] !== "=") return false;
  i--;
  while (i >= 0 && /\s/.test(text[i])) i--;
  return /[A-Za-z0-9_$:-]/.test(text[i] ?? "");
}

/** The raw symbol renders a bound name reaches. */
export function aliasFindings(text, name, from, inScope) {
  const findings = [];
  const escaped = name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const read = new RegExp(`\\b${escaped}\\b`, "g");
  let match;
  while ((match = read.exec(text)) !== null) {
    const index = match.index;
    // Only what comes after the binding is carried by it.
    if (index < from) continue;
    // The binding itself, a member of something else, a key written beside it.
    if (
      /(?:const|let|var)\s+$/.test(text.slice(Math.max(0, index - 12), index))
    )
      continue;
    if (text[index - 1] === ".") continue;
    if (/^\s*:/.test(text.slice(index + name.length, index + name.length + 4)))
      continue;
    const expr = bracedAround(text, index);
    if (isStatement(expr)) continue;
    const enclosing = enclosingCalls(text, index);
    if (enclosing.some((call) => inScope.includes(call.name))) continue;
    if (inScope.some((n) => expr.includes(`${n}(`))) continue;
    if (isPayloadObject(expr, enclosing)) continue;
    if (UNITS_KEY.test(expr)) continue;
    if (enclosing.some((call) => UNITS_KEY.test(call.args))) continue;
    if (enclosing.some((call) => TRANSLATORS.has(call.name))) {
      findings.push({ line: lineOf(text, index) });
      continue;
    }
    const { start } = braceBounds(text, index);
    if (isJsxAttributeValue(text, start)) continue;
    // A render shows the value itself: the braced expression opens with the
    // name, not with a call that merely receives it.
    const afterOpen = text.slice(start + 1).trimStart();
    if (!afterOpen.startsWith(name)) continue;
    if (/[A-Za-z0-9_$]/.test(afterOpen[name.length] ?? "")) continue;
    findings.push({ line: lineOf(text, index) });
  }
  return findings;
}

/** The raw symbol renders of one file. */
export function rawUnitsIn(rel, source) {
  const text = blankComments(source);
  const inScope = [...RESOLVERS, ...localResolvers(text)];
  const findings = [];
  SYMBOL_READ.lastIndex = 0;
  let match;
  while ((match = SYMBOL_READ.exec(text)) !== null) {
    const expr = bracedAround(text, match.index);
    if (isStatement(expr)) continue;
    // A resolver counts when it ENCLOSES the read: either inside the braced
    // expression, or as a call whose parentheses are still open here — which
    // is how a `defaultValue` object inside a `tDyn("common:units…")` call is
    // already resolved.
    const enclosing = enclosingCalls(text, match.index);
    if (isPayloadObject(expr, enclosing)) continue;
    if (
      inScope.some(
        (n) => expr.includes(`${n}(`) || enclosing.some((c) => c.name === n),
      )
    )
      continue;
    if (UNITS_KEY.test(expr)) continue;
    if (enclosing.some((c) => UNITS_KEY.test(c.args))) continue;
    // A value handed to a component as a prop is the consumer's to print, as
    // the header says — the bound-name path below already reads it that way.
    // A translator's argument stays a finding wherever it sits.
    if (
      !enclosing.some((c) => TRANSLATORS.has(c.name)) &&
      isJsxAttributeValue(text, braceBounds(text, match.index).start)
    )
      continue;
    findings.push({ file: rel, line: lineOf(text, match.index) });
  }
  for (const [name, from] of rawAliases(text, inScope)) {
    for (const { line } of aliasFindings(text, name, from, inScope)) {
      findings.push({ file: rel, line });
    }
  }
  return findings;
}

export function findingKey(f) {
  return f.file;
}

export function tally(findings) {
  const counts = new Map();
  for (const f of findings) {
    const key = findingKey(f);
    counts.set(key, (counts.get(key) ?? 0) + 1);
  }
  return counts;
}

export function diffBaseline(findings, baselineCounts) {
  const current = tally(findings);
  const base = new Map(Object.entries(baselineCounts ?? {}));
  const added = [];
  const fixed = [];
  for (const [key, count] of current) {
    const was = base.get(key) ?? 0;
    if (count > was) added.push({ key, was, now: count });
  }
  for (const [key, was] of base) {
    const now = current.get(key) ?? 0;
    if (now < was) fixed.push({ key, was, now });
  }
  return { added, fixed, current };
}

function main() {
  const args = process.argv.slice(2);
  const useBaseline = args.includes("--baseline");
  const writeBaseline = args.includes("--write-baseline");
  const quiet = args.includes("--quiet");

  const files = walk(SRC)
    .map((f) => relative(SRC, f).split("\\").join("/"))
    .filter(isScanned);

  const findings = files.flatMap((rel) =>
    rawUnitsIn(rel, readFileSync(resolve(SRC, rel), "utf8")),
  );

  if (writeBaseline) {
    writeFileSync(
      BASELINE_PATH,
      JSON.stringify(
        {
          raw: Object.fromEntries([...tally(findings)].sort()),
        },
        null,
        2,
      ) + "\n",
    );
    console.log(
      `quantity-render baseline written: ${findings.length} raw read(s) → scripts/quantity-render-baseline.json`,
    );
    process.exit(0);
  }

  const baseline =
    useBaseline && existsSync(BASELINE_PATH)
      ? JSON.parse(readFileSync(BASELINE_PATH, "utf8")).raw
      : {};
  const { added, fixed } = diffBaseline(findings, baseline);

  if (added.length > 0) {
    console.error(
      `\nquantity-render: ${added.length} NEW raw unit symbol render(s)\n`,
    );
    for (const { key, was, now } of added) {
      console.error(was === 0 ? `  ${key}` : `  ${key}  (${was} → ${now})`);
    }
    console.error(
      "\nPut the quantity and its unit through `formatQuantityLocalized(t, " +
        "quantity, symbol, rounding)` — it reads `common:units.<symbol>` for " +
        "the word and `uom.rounding` for the decimals, so the number stops " +
        "carrying the database's scale at the same time.",
    );
    process.exit(1);
  }

  if (!quiet) {
    const total = [...tally(findings).values()].reduce((a, b) => a + b, 0);
    console.log(
      `quantity-render: ${files.length} file(s) scanned, ${total} raw read(s) (all in the baseline).`,
    );
    if (fixed.length > 0) {
      console.log(
        `✓ ${fixed.length} baseline entr(y/ies) improved — run --write-baseline to refresh.`,
      );
    }
  }
  process.exit(0);
}

if (
  process.argv[1] &&
  resolve(process.argv[1]) === fileURLToPath(import.meta.url)
) {
  main();
}
