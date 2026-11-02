#!/usr/bin/env node
/**
 * check-theme-colors.mjs
 *
 * A colour class that the theme does not define compiles to no CSS rule at
 * all: it survives TypeScript, eslint, the unit tests and the token-contrast
 * gate (which reads variables in index.css, never class names), and the text
 * it was meant to colour inherits the body colour. Measured on a live stack
 * before this gate existed: `text-warning-600` and `text-warning-400`
 * rendered rgb(17, 24, 39) — byte-identical to no class — on every warning
 * that carried them, so warnings written amber in code read on screen as an
 * ordinary sentence.
 *
 * The theme defines numeric ramps for primary, accent, success, gray and the
 * light 50–200 steps of red/amber/blue; every other colour name — including
 * the status names `warning`, `danger` and `info` — exists only as a token
 * half: `text-on-warning` pairs with its tint and needs no `dark:` override
 * (UI_GUIDELINES §2, "never a ramp step"). Both halves are checked here
 * against the palette Tailwind itself resolves (defaults merged with
 * tailwind.config.js), so a ramp added to the config starts passing without
 * this script learning about it, and a name removed starts failing.
 *
 * Checked, because resolvable without Tailwind semantics:
 *   - `<utility>-<name>-<step>` for the colour-bearing utilities
 *     (text, bg, border, ring) — the name must exist in the utility's
 *     namespace and the step in that name's ramp; both misses compile to
 *     nothing (`text-primary-999` no less than `text-warning-600`);
 *   - `text-on-<name>` — the token the guidelines mandate, whose typo would
 *     otherwise render as body text.
 *
 * Deliberately unchecked: the bare form (`text-center`, `bg-cover`,
 * `text-primary`) is ambiguous without knowing which CSS property each
 * utility maps to, and arbitrary values (`text-[10px]`) resolve at build
 * time. The exception that proves it: a bare form of a STATUS name —
 * `text-danger`, `bg-warning/50` — is unambiguous, because those four names
 * exist in no shape at all (no ramp in the config, no bare colour), so the
 * class can only be an attempt at the status colour that compiles to
 * nothing. Status text goes through `text-on-<name>`. Interpolation
 * (`` `text-${name}-600` ``) is invisible to any scanner and is the caller's
 * responsibility.
 *
 * Zero-tolerance: no baseline, because the whole debt is the handful of
 * lines this branch rewrites and a gate born with a grandfather clause would
 * never see the next one.
 *
 * Modes:
 *   node check-theme-colors.mjs          # report, exit 1 on findings
 *   node check-theme-colors.mjs --quiet  # exit code only
 */
import { readFileSync, readdirSync } from "node:fs";
import { relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import resolveConfig from "tailwindcss/resolveConfig.js";
import tailwindConfig from "../tailwind.config.js";

// `new URL(...).pathname`, not fileURLToPath: under vitest `import.meta.url`
// carries a `/@fs/` prefix that fileURLToPath refuses outright — and the
// prefix has to come off before resolve(), or the CLI-only walk below tries
// to scandir a path that was never on disk.
const HERE = new URL(".", import.meta.url).pathname.replace(/^\/@fs/, ""); // scripts/
const ROOT = resolve(HERE, ".."); // frontend/
const SRC = resolve(ROOT, "src");

/** Built-in colour keywords Tailwind always provides, defined outside the theme. */
const BUILT_INS = new Set(["inherit", "current", "transparent"]);

/**
 * Colour name → its defined steps, per utility namespace, as Tailwind
 * resolves it (config extend merged over the default palette). A string
 * value means the name has no steps — only the bare form exists.
 */
const resolved = resolveConfig(tailwindConfig).theme;
const NAMESPACES = {
  text: resolved.textColor,
  bg: resolved.backgroundColor,
  border: resolved.borderColor,
  ring: resolved.ringColor,
};
/** `text-on-*` is the one compound the guidelines name; its keys live here. */
const ON_TOKENS = new Set(
  resolved.textColor?.on ? Object.keys(resolved.textColor.on) : [],
);
/**
 * Status names with no theme definition in any form — no ramp, no bare
 * colour. A bare (step-less, optionally /opacity) class carrying one of
 * these names compiles to nothing, and unlike `text-primary` vs
 * `text-center` the name alone says so: no real utility wears them.
 */
const STATUS_NAMES = new Set(["warning", "danger", "info", "error"]);

export function isScanned(rel) {
  if (!/\.tsx?$/.test(rel)) return false;
  if (/\.test\.tsx?$/.test(rel)) return false;
  return true;
}

function colorNameExists(utility, name) {
  const ns = NAMESPACES[utility];
  if (!ns) return false;
  return name in ns || BUILT_INS.has(name);
}

function stepExists(utility, name, step) {
  const value = NAMESPACES[utility]?.[name];
  return typeof value === "object" && value !== null && step in value;
}

/**
 * The colour part of a border or ring class: `l-danger` and `offset-danger`
 * are the side or offset and then the colour, so `danger` is what to judge.
 * Every other utility has no such prefix.
 */
function withoutSidePrefix(rest) {
  const prefixed = rest.match(/^(?:[trblxyse]|offset)-(.+)$/);
  return prefixed ? prefixed[1] : rest;
}

/**
 * `{ name, step }` for a numeric colour class, or null when the token is not
 * one the scanner can judge.
 *
 * Border and ring carry width utilities on the same prefix that colours ride:
 * `border-b-2`, `border-l-4` and `ring-offset-2` are widths (a side/offset
 * prefix on a bare number), while `border-l-accent-500` is a colour on a
 * side. A colour name the theme lacks plus a numeric step is exactly the
 * defect shape — it compiles to nothing just like a missing name.
 */
function parseColorClass(utility, rest) {
  let candidate = rest;
  if (utility === "border" || utility === "ring") {
    candidate = withoutSidePrefix(rest);
    if (/^\d+$/.test(candidate)) return null; // border-b-2, ring-offset-2
    if (candidate.startsWith("spacing")) return null; // border-spacing-y-0
  }
  const step = candidate.match(/^(.+)-(\d+)$/);
  return step ? { name: step[1], step: step[2] } : null;
}

/**
 * Findings in one file, as `{ rule, line, text }`.
 *
 * Line-scoped rather than string-scoped on purpose: a class list is often a
 * template literal with interpolation, and a scan that only understands plain
 * string literals misses exactly the conditional classes most likely to drift.
 */
export function findingsIn(rel, text) {
  const out = [];
  const lines = text.split("\n");

  lines.forEach((line, i) => {
    const at = { file: rel, line: i + 1 };

    for (const m of line.matchAll(
      /\b(text|bg|border|ring)-([a-z][a-z0-9-]*)/g,
    )) {
      const [, utility, rest] = m;
      const token = m[0].split(":").pop(); // `dark:text-warning-400` → the class

      // A trailing dash is prose (`the text-on-* half` in a comment) or the
      // head of an interpolation — not a complete class; both unjudgeable.
      if (rest.endsWith("-")) continue;

      const color = parseColorClass(utility, rest);
      if (color) {
        if (!colorNameExists(utility, color.name)) {
          out.push({ ...at, rule: "no-such-color", text: token });
        } else if (!stepExists(utility, color.name, color.step)) {
          out.push({ ...at, rule: "no-such-step", text: token });
        }
        continue;
      }

      // The sanctioned token pair half: `text-on-warning`, `text-on-muted`.
      if (utility === "text" && rest.startsWith("on-")) {
        if (!ON_TOKENS.has(rest.slice(3))) {
          out.push({ ...at, rule: "no-such-on-token", text: token });
        }
        continue;
      }

      // A bare status name — `text-danger`, `bg-warning/50` — is the one
      // unambiguous bare form: those names exist in no shape, so the class
      // is a status colour that compiles to nothing.
      const bare =
        utility === "border" || utility === "ring"
          ? withoutSidePrefix(rest)
          : rest;
      if (STATUS_NAMES.has(bare)) {
        out.push({ ...at, rule: "no-such-color", text: token });
      }
      // Every other bare form is ambiguous (text-center vs text-primary)
      // and stays unchecked — see the header.
    }
  });

  return out;
}

function walk(dir, out = []) {
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const full = resolve(dir, entry.name);
    if (entry.isDirectory()) walk(full, out);
    else out.push(full);
  }
  return out;
}

function main() {
  const quiet = process.argv.includes("--quiet");
  const findings = [];
  for (const path of walk(SRC)) {
    const rel = relative(ROOT, path);
    if (!isScanned(rel)) continue;
    findings.push(...findingsIn(rel, readFileSync(path, "utf8")));
  }

  if (!quiet) {
    if (findings.length === 0) {
      console.log(
        "check-theme-colors: every colour class resolves in the theme",
      );
    } else {
      for (const f of findings) {
        console.log(
          `${f.file}:${f.line}: ${f.rule}: ${f.text} — no such colour in the resolved theme`,
        );
      }
      console.log(
        `\n${findings.length} finding(s). A class the theme does not define compiles to no rule; ` +
          "pair status text with its text-on-* token or add the ramp to tailwind.config.js.",
      );
    }
  }
  process.exitCode = findings.length > 0 ? 1 : 0;
}

if (
  process.argv[1] &&
  resolve(process.argv[1]) === resolve(HERE, "check-theme-colors.mjs")
) {
  main();
}
