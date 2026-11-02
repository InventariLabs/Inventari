#!/usr/bin/env node
/**
 * lint-i18n-raw.mjs
 *
 * Flags hardcoded user-facing English strings that bypass the i18n layer.
 * Designed to fail CI on any new regressions so we don't get "English text
 * appears in the German build" bug reports back.
 *
 * Scope:
 *   - toast.success|error|info|warning|loading|message|dismiss(...)
 *     when the argument is a bare string literal (not template, not t())
 *   - window.alert(...) / window.confirm(...)
 *   - aria-label="..." / alt="..." / placeholder="..." JSX attributes with a
 *     bare string literal. Decision recorded here: these attributes
 *     ARE covered — they were the one class of user-facing literals that
 *     passed the gate without a trace, and four of the five findings
 *     were exactly this shape. Language-neutral tokens are allowed: codes and
 *     symbols without lowercase letters (PZ, LOC-001, "—", "•••"), e-mail
 *     examples (name@example.com), URLs, hostnames (smtp.gmail.com), paths /
 *     model ids (google/gemini-2.0-flash-001) and tech placeholders
 *     (<html>...). Prose with lowercase letters is always flagged.
 *   - a JSX text node that is prose — the two findings that prompted it ("Active
 *     list" on the inventory dashboard, "Oops! Something went wrong" on the
 *     router's error screen) were exactly this shape. The rule used to be
 *     switched off here with "too many false positives (icons, whitespace,
 *     etc.) to do reliably from a regex"; measured on the tree when the
 *     regex was replaced by an AST walk, the exclusion was false — the
 *     walk flags a text node only when it carries a word of three letters
 *     or more and is not a name or a symbol (see FIXED_TEXT/UNIT_SYMBOLS).
 *     A code or a punctuation mark has no such word, which is what makes
 *     the rule safe without an allowlist.
 *   - a name/label/title string literal inside a module-scope array of
 *     option objects — seven label-size presets once lived there,
 *     in a `{ name: "Small (38x15)" }` shape no regex can tell from a config
 *     table. Objects that describe a third-party service (they carry a
 *     `logo`, `docsUrl` or `defaultBaseUrl` of their own) are exempt on
 *     purpose: a provider keeps its own name in every language, which is why
 *     the provider list is translated through `labelKey`/`name` alone.
 *   - a template literal glued around a t() interpolation — the shape
 *     `${t("…")} (${qty} left)`, which passed every rule above
 *     because the English word sat outside the `t()` call. The rule fires
 *     only when the interpolated expression really is a `t()` call and the
 *     literal text beside it carries prose; a URL or a path is neutral.
 *
 * The three node-shaped rules arrived together, and what they cost is on the
 * record because the old comment here claimed the opposite. Measured on
 * 2026-09-18: the rule set below read **0
 * violations** on a file carrying one planted instance of each shape, and
 * **21** on the tree it had been guarding — a JSX text node, an option-table
 * label, and the glued template each sat behind a green gate. All 21 are
 * fixed in the change that added the rules, so the gate is green because the
 * tree is clean, not because the rules look away.
 *
 * Out of scope (intentional):
 *   - Interpolation placeholders {{ like }} inside t() defaultValue strings
 *     are correct i18next syntax
 *   - Tests / __tests__/ / __mocks__/ — they are allowed to use bare
 *     English to assert rendered output
 *   - A single-word text node that is a name or a symbol — "Inventari",
 *     "Nutri", "kcal". The boundary is honest rather than complete: "Yes"
 *     and "Prev" are three and four letters and are flagged, so the rule
 *     does catch single words; what it cannot do without a dictionary is
 *     tell a brand from a verb. Those go in FIXED_TEXT with a reason.
 *   - A bare string literal rendered from a JSX expression container —
 *     `{cond ? "create" : "edit"}`. Tried and withdrawn in the same change:
 *     234 findings on the tree, and almost every one of them was a key or a
 *     comparable value (`modal.type === "create"`, `i18next.t("…")`) that no
 *     walk of this depth can tell from a sentence. Catching them needs the
 *     kinds a type checker knows, not the kinds a syntax tree does.
 *
 * Usage:
 *   node frontend/scripts/lint-i18n-raw.mjs          # exit 1 on violations
 *   node frontend/scripts/lint-i18n-raw.mjs --quiet  # only summary
 */
import { readFileSync, readdirSync, statSync } from "node:fs";
import { resolve, relative, join } from "node:path";
import { pathToFileURL } from "node:url";
import ts from "typescript";

const ROOT = resolve(new URL("..", import.meta.url).pathname);
const SEARCH_DIRS = ["src/modules", "src/components", "src/pages", "src/app"];
const SKIP_PATH_PARTS = ["__tests__", "__mocks__", "/test/", "/tests/"];
const SKIP_FILES = new Set(["setup.ts"]);
// Colocated specs sit next to the component, not in __tests__ — skip them too,
// otherwise the attribute check fires on assertions, not on shipped UI.
const SKIP_FILE_RE = /\.(test|spec)\.[tj]sx?$/;

const TOAST_METHODS = [
  "success",
  "error",
  "info",
  "warning",
  "loading",
  "message",
  "dismiss",
  "promise",
];

const PATTERNS = [
  {
    re: new RegExp(
      `\\btoast\\.(${TOAST_METHODS.join("|")})\\(\\s*"([^"$\\n]{4,})"`,
      "g",
    ),
    attr: false,
  },
  { re: /\bwindow\.(alert|confirm)\(\s*"([^"$\n]{4,}?)"/g, attr: false },
  { re: /\b(aria-label|alt|placeholder)\s*=\s*"([^"$\n]{2,})"/g, attr: true },
];

// an attribute literal is language-neutral — and therefore fine —
// when it carries no prose: codes/symbols with no lowercase letters, e-mail
// examples, URLs, hostnames, paths/model ids, or a <tag>... tech placeholder.
const looksLanguageNeutral = (s) =>
  !/\p{Ll}/u.test(s) ||
  s.includes("@") ||
  /^https?:\/\//.test(s) ||
  s.includes("/") ||
  /^[\w.-]+\.[\w.-]+$/.test(s) ||
  /^<[a-z]+>(\.\.\.)?$/i.test(s);

// Guard: a template literal containing `{t(` NOT preceded by
// `$` means a missing `$` before the brace — the i18n key renders
// verbatim (e.g. `{t("item.barcode")}: ...` instead of "Barcode: ...").
// Legitimate interpolations always look like `${t("...")}`.
const T17_TEMPLATE_KEY = /`[^`]*[^$]\{t\(/g;

const allowIfLooksLikeI18nKey = (s) =>
  /^[a-z][a-z0-9_]*(\.[a-z0-9_]+)+$/i.test(s);

// ---------------------------------------------------------------------------
// What a text is allowed to be in a translated interface
// ---------------------------------------------------------------------------

/**
 * Text nodes that stay as written in every language: a product's or a
 * standard's own name, and the lockups built out of them. Every entry is a
 * decision, and the reason is the same for all of them — a source is cited,
 * not translated. Adding one here is a claim that the string names something
 * (`Inventari`, `Nutri-Score`) rather than says something.
 */
const FIXED_TEXT = new Set([
  "Inventari",
  "Inventari Ecosystem",
  "Nutri",
  "Fluent",
  "Open Food Facts",
  "ODbL",
]);

/**
 * Units and symbols carry no language. Written lowercase in most catalogs,
 * they are the one family of short lowercase words a text node may hold.
 */
const UNIT_SYMBOLS = new Set([
  "g",
  "kg",
  "mg",
  "ml",
  "l",
  "mm",
  "cm",
  "m",
  "kcal",
  "kj",
  "pcs",
  "szt",
  "h",
  "min",
  "s",
  "c",
  "f",
]);

/** `&rarr;`, `&middot;` — an entity is markup, not a word, so it is removed
 *  before the text is read: leaving it in turns `Inventari &middot;` into a
 *  sentence with the word "middot" in it. */
const HTML_ENTITY_RE = /&[a-zA-Z]+;/g;

/** A lowercase identifier — `announcements`, `storage_location` — is a name
 *  the code gives a thing, not a sentence a reader reads. */
const TECHNICAL_ID_RE = /^[a-z][a-z0-9_]*$/;

/** Letters only: `Fluent ·` normalises to `Fluent`. */
const normaliseForLookup = (s) =>
  s
    .replace(/[^\p{L}\p{N}]+/gu, " ")
    .replace(/\s+/g, " ")
    .trim();

const isFixedText = (text) => {
  const key = normaliseForLookup(text);
  return FIXED_TEXT.has(key) || UNIT_SYMBOLS.has(key);
};

/** At least one run of letters long enough to be a word rather than a tick. */
const carriesWord = (s) =>
  s.split(/[^\p{L}]+/u).some((w) => w.length >= 3 && /\p{Ll}/u.test(w));

// ---------------------------------------------------------------------------
// Regex rules — line at a time, as before
// ---------------------------------------------------------------------------

function checkLines(rel, text, report) {
  const lines = text.split(/\r?\n/);

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    for (const { re: pat, attr } of PATTERNS) {
      pat.lastIndex = 0;
      let m;
      while ((m = pat.exec(line)) !== null) {
        const literal = m[2];
        if (allowIfLooksLikeI18nKey(literal)) continue;
        if (/^[\d.]+$/.test(literal)) continue;
        if (attr && looksLanguageNeutral(literal)) continue;
        report(
          attr
            ? `${rel}:${i + 1}: raw string "${literal.slice(0, 60)}" in ${m[1]}= attribute`
            : `${rel}:${i + 1}: raw string "${literal.slice(0, 60)}" passed directly to ${m[1]}()`,
        );
      }
    }
    T17_TEMPLATE_KEY.lastIndex = 0;
    let m17;
    while ((m17 = T17_TEMPLATE_KEY.exec(line)) !== null) {
      report(
        `${rel}:${i + 1}: template literal contains \`{t(\` without \`$\` — missing interpolation?`,
      );
    }
  }
}

// ---------------------------------------------------------------------------
// AST rules — line at a time cannot see a node, and these three are nodes
// ---------------------------------------------------------------------------

const isServiceDescriptor = (objectLiteral) =>
  objectLiteral.properties.some(
    (p) =>
      ts.isPropertyAssignment(p) &&
      ts.isIdentifier(p.name) &&
      ["logo", "docsUrl", "defaultBaseUrl"].includes(p.name.text),
  );

const stringOf = (node) =>
  ts.isStringLiteral(node) || ts.isNoSubstitutionTemplateLiteral(node)
    ? node.text
    : null;

function checkAst(rel, text, kind, report) {
  const source = ts.createSourceFile(
    rel,
    text,
    ts.ScriptTarget.Latest,
    /* setParentNodes */ true,
    kind,
  );
  const lineOf = (node) =>
    source.getLineAndCharacterOfPosition(node.getStart(source)).line + 1;

  const visit = (node) => {
    // 1. A bare text node between two tags.
    if (ts.isJsxText(node)) {
      const shown = node.text
        .replace(HTML_ENTITY_RE, " ")
        .replace(/\s+/g, " ")
        .trim();
      if (shown && !isFixedText(shown) && carriesWord(shown)) {
        report(
          `${rel}:${lineOf(node)}: raw JSX text node "${shown.slice(0, 60)}" — move it through t()`,
        );
      }
    }

    // 2. A label literal inside a table of options.
    if (ts.isVariableDeclaration(node) && ts.isIdentifier(node.name)) {
      const isModuleScope = ts.isSourceFile(node.parent?.parent?.parent);
      const initializer =
        node.initializer && ts.isAsExpression(node.initializer)
          ? node.initializer.expression
          : node.initializer;
      if (isModuleScope && initializer && ts.isArrayLiteralExpression(initializer)) {
        for (const element of initializer.elements) {
          if (!ts.isObjectLiteralExpression(element)) continue;
          if (isServiceDescriptor(element)) continue;
          for (const prop of element.properties) {
            if (!ts.isPropertyAssignment(prop)) continue;
            if (!ts.isIdentifier(prop.name)) continue;
            if (!["name", "label", "title"].includes(prop.name.text)) continue;
            const value = stringOf(prop.initializer);
            if (!value) continue;
            if (allowIfLooksLikeI18nKey(value)) continue;
            if (TECHNICAL_ID_RE.test(value)) continue;
            if (!carriesWord(value)) continue;
            report(
              `${rel}:${lineOf(prop)}: raw string "${value.slice(0, 60)}" in a rendered ${prop.name.text} — move it through t()`,
            );
          }
        }
      }
    }

    // 3. English glued onto a t() interpolation inside one template literal.
    if (ts.isTemplateExpression(node)) {
      const interpolatesT = node.templateSpans.some((span) => {
        const expr = span.expression;
        return (
          ts.isCallExpression(expr) &&
          ts.isIdentifier(expr.expression) &&
          expr.expression.text === "t"
        );
      });
      if (interpolatesT) {
        const chunks = [
          node.head.text,
          ...node.templateSpans.map((span) => span.literal.text),
        ];
        const prose = chunks.find((chunk) => {
          const raw = chunk.trim();
          if (!raw || looksLanguageNeutral(raw)) return false;
          const stripped = raw
            .replace(/[a-z]+:\/\/\S*/gi, "")
            .replace(/[^\p{L}\s]+/gu, " ");
          return carriesWord(stripped);
        });
        if (prose !== undefined) {
          report(
            `${rel}:${lineOf(node)}: raw string "${prose.trim().slice(0, 60)}" beside a t() interpolation — one key, not a sentence built from parts`,
          );
        }
      }
    }

    ts.forEachChild(node, visit);
  };

  ts.forEachChild(source, visit);
}

// ---------------------------------------------------------------------------
// Walking and reporting
// ---------------------------------------------------------------------------

/**
 * Every violation in the given files, as text lines. Exported so the rule
 * itself can be tested: a lint whose failures nobody can plant is a lint
 * nobody can trust.
 */
export function findViolations(files) {
  const found = [];
  const report = (line) => found.push(line);
  for (const file of files) {
    if (SKIP_FILE_RE.test(file.path) || SKIP_FILES.has(file.path)) continue;
    checkLines(file.path, file.text, report);
    const kind = /\.tsx$/.test(file.path) ? ts.ScriptKind.TSX : ts.ScriptKind.TS;
    checkAst(file.path, file.text, kind, report);
  }
  return found;
}

function walk(dir, out = []) {
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const full = join(dir, entry.name);
    if (entry.isDirectory()) {
      if (SKIP_PATH_PARTS.some((p) => full.includes(p))) continue;
      walk(full, out);
    } else if (/\.(tsx?|jsx?)$/.test(entry.name)) {
      out.push(full);
    }
  }
  return out;
}

function collectFiles() {
  const files = [];
  for (const d of SEARCH_DIRS) {
    try {
      const abs = resolve(ROOT, d);
      if (statSync(abs).isDirectory()) walk(abs, files);
    } catch {
      /* missing dir is OK */
    }
  }
  return files.map((full) => ({
    path: relative(ROOT, full),
    text: readFileSync(full, "utf8"),
  }));
}

// Only run the CLI when executed, not when imported by the test.
if (import.meta.url === pathToFileURL(process.argv[1] ?? "").href) {
  const quiet = process.argv.includes("--quiet");
  const violations = findViolations(collectFiles());

  for (const line of violations) console.error(line);

  if (quiet && violations.length > 0) {
    console.error(`\nlint-i18n-raw: ${violations.length} violation(s)`);
  } else if (violations.length === 0) {
    console.log("lint-i18n-raw: 0 violations");
  }

  if (violations.length > 0) process.exit(1);
}
