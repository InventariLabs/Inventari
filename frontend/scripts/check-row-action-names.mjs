#!/usr/bin/env node
/**
 * check-row-action-names.mjs
 *
 * A row's action has to say which row it acts on. "Revoke" repeated eight
 * times, "Edit connection" on every connection, "Activate" on fourteen
 * modules: a screen reader moving through the list by button hears the same
 * name each time and cannot tell which record the press will change. Sighted
 * readers get the row from the layout; nothing else does.
 *
 * The class has come back three times in the 2026-11 QA round — API keys,
 * AI connections and the module store in the first-contact walk, then product
 * rows, category cards, archived assets and the label pool, then equipment
 * rows, recipe tags, approval cards and replenish suggestions. It was first
 * closed for a handful of screens, which is why a per-screen fix kept buying
 * the next round another ticket.
 *
 * The rule reads a control inside a `.map(…)` over a collection: its
 * accessible name is its `aria-label`, or — when there is none — its visible
 * text, or its `title` for an icon-only control. That name passes when it
 * mentions something derived from the map's row: the parameter, a property
 * destructured from it, or a name bound in the callback from one of those.
 * `aria-labelledby` names the control by another element and is not read
 * here.
 *
 * Modes:
 *   node check-row-action-names.mjs                    # report and exit 1
 *   node check-row-action-names.mjs --baseline         # only NEW findings fail
 *   node check-row-action-names.mjs --write-baseline   # snapshot current
 *   node check-row-action-names.mjs --quiet            # exit code only
 *
 * Baseline: frontend/scripts/row-action-baseline.json (one entry per file
 * and constant name). The goal is an empty baseline.
 */
import { existsSync, readFileSync, readdirSync, writeFileSync } from "node:fs";
import { join, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import ts from "typescript";

const ROOT = resolve(new URL("..", import.meta.url).pathname); // frontend/
const SRC = resolve(ROOT, "src");
const BASELINE_PATH = resolve(ROOT, "scripts/row-action-baseline.json");

/** Tags that are a control a reader can press, whatever their props. */
const CONTROL_TAGS = new Set([
  "Button",
  "IconButton",
  "MenuItem",
  "DropdownMenuItem",
  "Link",
  "a",
  "button",
]);

function walk(dir, out = []) {
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const full = join(dir, entry.name);
    if (entry.isDirectory()) walk(full, out);
    else out.push(full);
  }
  return out;
}

export function isScanned(rel) {
  if (!rel.endsWith(".tsx")) return false;
  // Module surfaces own their rows; the shell's lists are pickers and
  // settings of the reader's own account, not records.
  if (!/^modules\//.test(rel)) return false;
  if (/\.test\.tsx$/.test(rel)) return false;
  if (/(^|\/)(test|__tests__|types)\//.test(rel)) return false;
  return true;
}

const attribute = (element, name) =>
  element.attributes.properties.find(
    (property) =>
      ts.isJsxAttribute(property) && property.name.getText() === name,
  );

/** The element whose children are the control's visible label. */
const withChildren = (element) =>
  ts.isJsxOpeningElement(element) && ts.isJsxElement(element.parent)
    ? element.parent
    : element;

/** The child text and expressions that make up an element's visible label. */
function childrenLabel(element) {
  const holder = withChildren(element);
  if (!holder.children || holder.children.length === 0) return null;
  const texts = holder.children
    .filter((child) => ts.isJsxText(child))
    .map((child) => child.text.trim())
    .filter(Boolean);
  const nodes = holder.children
    .filter((child) => ts.isJsxExpression(child) && Boolean(child.expression))
    .map((child) => textual(child.expression))
    .filter(Boolean);
  if (texts.length === 0 && nodes.length === 0) return null;
  return {
    nodes,
    text: [...texts, ...nodes.map((node) => node.getText())].join(" "),
  };
}

/** The part of an expression that renders as text, or null for markup. */
function textual(node) {
  if (ts.isParenthesizedExpression(node)) return textual(node.expression);
  if (
    ts.isJsxElement(node) ||
    ts.isJsxSelfClosingElement(node) ||
    ts.isJsxFragment(node)
  ) {
    return null;
  }
  if (ts.isConditionalExpression(node)) {
    const whenTrue = textual(node.whenTrue);
    const whenFalse = textual(node.whenFalse);
    if (!whenTrue && !whenFalse) return null;
    return whenTrue ?? whenFalse;
  }
  if (
    ts.isBinaryExpression(node) &&
    node.operatorToken.kind === ts.SyntaxKind.AmpersandAmpersandToken
  ) {
    return textual(node.right);
  }
  return node;
}

/** The accessible name of the control as label expressions and text. */
function accessibleName(element) {
  // Named by another element: the name is that element's, not this markup's.
  if (attribute(element, "aria-labelledby")) return null;
  const labelAttr = attribute(element, "aria-label");
  if (labelAttr?.initializer) {
    if (ts.isStringLiteral(labelAttr.initializer))
      return { nodes: [], text: labelAttr.initializer.text };
    if (
      ts.isJsxExpression(labelAttr.initializer) &&
      labelAttr.initializer.expression
    )
      return {
        nodes: [labelAttr.initializer.expression],
        text: labelAttr.initializer.getText(),
      };
  }
  const children = childrenLabel(element);
  if (children) return children;
  const titleAttr = attribute(element, "title");
  if (titleAttr?.initializer) {
    if (ts.isStringLiteral(titleAttr.initializer))
      return { nodes: [], text: titleAttr.initializer.text };
    if (
      ts.isJsxExpression(titleAttr.initializer) &&
      titleAttr.initializer.expression
    )
      return {
        nodes: [titleAttr.initializer.expression],
        text: titleAttr.initializer.getText(),
      };
  }
  return null;
}

/** The local names a row parameter binds. */
function rowNames(parameter) {
  if (!parameter) return [];
  if (ts.isIdentifier(parameter.name)) return [parameter.name.text];
  if (ts.isObjectBindingPattern(parameter.name)) {
    return parameter.name.elements
      .map((element) =>
        ts.isIdentifier(element.name) ? element.name.text : null,
      )
      .filter(Boolean);
  }
  return [];
}

/** Words that appear in `text` as an identifier. */
function mentions(text, names) {
  return names.some((name) =>
    new RegExp(String.raw`\b${name.replace(/\$/g, "\\$")}\b`).test(text),
  );
}

/**
 * Does the rendered label name the row anywhere?
 *
 * The condition choosing between two labels does not: `enabled ? "Disable" :
 * "Enable"` says which state the row is in, not which row it is, and that is
 * exactly the module store's fourteen identical buttons. A branch's text or
 * its interpolation does name the row.
 */
function labelNamesRow(node, names) {
  let found = false;
  const visit = (current) => {
    if (found) return;
    if (
      ts.isIdentifier(current) &&
      names.includes(current.text) &&
      !(
        ts.isPropertyAccessExpression(current.parent) &&
        current.parent.name === current
      ) &&
      !(
        ts.isPropertyAssignment(current.parent) &&
        current.parent.name === current
      )
    ) {
      found = true;
      return;
    }
    if (ts.isConditionalExpression(current)) {
      visit(current.whenTrue);
      visit(current.whenFalse);
      return;
    }
    if (
      ts.isBinaryExpression(current) &&
      [
        ts.SyntaxKind.AmpersandAmpersandToken,
        ts.SyntaxKind.BarBarToken,
        ts.SyntaxKind.QuestionQuestionToken,
      ].includes(current.operatorToken.kind)
    ) {
      visit(current.right);
      return;
    }
    ts.forEachChild(current, visit);
  };
  visit(node);
  return found;
}

/**
 * The callback's own bindings that carry the row: `const id = row.id` makes
 * `id` row-derived, and a name built from it names the row.
 */
function derivedInside(body, names) {
  const derived = new Set(names);
  const visit = (node) => {
    if (ts.isVariableDeclaration(node)) {
      const bound = ts.isIdentifier(node.name)
        ? [node.name.text]
        : ts.isObjectBindingPattern(node.name)
          ? node.name.elements
              .map((element) =>
                ts.isIdentifier(element.name) ? element.name.text : null,
              )
              .filter(Boolean)
          : [];
      const initializer = node.initializer?.getText() ?? "";
      if (bound.length > 0 && mentions(initializer, [...derived])) {
        for (const name of bound) derived.add(name);
      }
    }
    ts.forEachChild(node, visit);
  };
  visit(body);
  return [...derived];
}

/** The label as a person would recognise it, for the baseline. */
function labelOf(name) {
  const match = /t\(\s*["']([^"']+)["']/.exec(name);
  if (match) return match[1];
  return name
    .replace(/\s+/g, " ")
    .replace(/^\{|\}$/g, "")
    .trim();
}

const isMapCall = (node) =>
  ts.isCallExpression(node) &&
  ts.isPropertyAccessExpression(node.expression) &&
  node.expression.name.text === "map";

/** The row names in scope at a control, for a card rendered per row. */
function namesAt(node) {
  for (let cur = node.parent; cur; cur = cur.parent) {
    if (
      ts.isFunctionLike(cur) &&
      cur.parameters[0] &&
      ts.isObjectBindingPattern(cur.parameters[0].name)
    ) {
      return derivedInside(cur.body ?? cur, rowNames(cur.parameters[0]));
    }
  }
  return [];
}

function findingsIn(source, rel, checker, { translatedOnly = false } = {}) {
  const out = [];
  const seen = new Set();
  const scan = (node) => {
    if (
      (ts.isJsxOpeningElement(node) || ts.isJsxSelfClosingElement(node)) &&
      isControl(node, source)
    ) {
      const name = accessibleName(node);
      const translated =
        /^(?:t|tDyn|tDynamic)\s*\(/.test(name?.text ?? "") ||
        /^["'`]/.test(name?.text ?? "");
      if (name && (!translatedOnly || translated) && !checker(name)) {
        const label = labelOf(name.text);
        if (label && !seen.has(label)) {
          seen.add(label);
          out.push({
            file: rel,
            line:
              source.getLineAndCharacterOfPosition(node.getStart()).line + 1,
            label,
          });
        }
      }
    }
    ts.forEachChild(node, scan);
  };
  scan(source);
  return out;
}

/**
 * Findings in one file: `{ line, label }`.
 *
 * `whole` reads every control in the file as a row action — the shape where
 * a page renders one card component per module and that card owns the
 * button, so no `.map` sits in the same file as the name.
 */
export function rowActionNamesIn(rel, text, { whole = false } = {}) {
  const source = ts.createSourceFile(
    rel,
    text,
    ts.ScriptTarget.Latest,
    /* setParentNodes */ true,
    ts.ScriptKind.TSX,
  );
  const out = [];
  const seen = new Set();
  const add = (findings) => {
    for (const finding of findings) {
      if (seen.has(finding.label)) continue;
      seen.add(finding.label);
      out.push(finding);
    }
  };

  if (whole) {
    add(
      findingsIn(
        source,
        rel,
        (name) =>
          name.nodes.some((expr) =>
            labelNamesRow(expr, namesAt(name.nodes[0])),
          ),
        { translatedOnly: true },
      ),
    );
  }

  const visit = (node) => {
    if (isMapCall(node) && node.arguments.length > 0) {
      const callback = node.arguments[0];
      if (ts.isArrowFunction(callback) || ts.isFunctionExpression(callback)) {
        const names = derivedInside(
          callback.body,
          rowNames(callback.parameters[0]),
        );
        const scan = (inner) => {
          // A nested map is a row of its own and is scanned on its own terms:
          // the outer row's name says nothing about the inner one.
          if (inner !== callback.body && isMapCall(inner)) return;
          if (
            (ts.isJsxOpeningElement(inner) ||
              ts.isJsxSelfClosingElement(inner)) &&
            isControl(inner, source)
          ) {
            const name = accessibleName(inner);
            if (
              name &&
              !name.nodes.some((expr) =>
                labelNamesRow(expr, [...names, ...namesAt(expr)]),
              )
            ) {
              const label = labelOf(name.text);
              if (label && !seen.has(label)) {
                seen.add(label);
                out.push({
                  file: rel,
                  line:
                    source.getLineAndCharacterOfPosition(inner.getStart())
                      .line + 1,
                  label,
                });
              }
            }
          }
          ts.forEachChild(inner, scan);
        };
        scan(callback.body);
      }
    }
    ts.forEachChild(node, visit);
  };
  visit(source);
  return out;
}

/**
 * The component files a render passes a row to.
 *
 * A page that renders `<ModuleCard module={mod} />` from inside its map has
 * put the row's actions in the card: the card's button is the row action,
 * and reading only the page would call the module store clean while fourteen
 * "Activate" buttons sit one file away.
 */
export function rowComponentPaths(files) {
  const byPath = new Map(files.map((file) => [file.path, file]));
  const out = new Set();
  for (const file of files) {
    if (!file.path.endsWith(".tsx")) continue;
    const imports = new Map();
    for (const match of file.text.matchAll(
      /import\s+(?:type\s+)?([^"']+?)\s+from\s+"(@\/[^"]+)"/g,
    )) {
      const names = [];
      const named = /\{([^}]*)\}/.exec(match[1]);
      if (named) {
        for (const binding of named[1].split(",")) {
          const name = binding
            .trim()
            .split(/\s+as\s+/)
            .pop()
            .trim();
          if (name) names.push(name);
        }
      }
      const fallback = /^\s*([A-Za-z_$][\w$]*)\s*(?:,|$)/.exec(match[1]);
      if (fallback && !match[1].trim().startsWith("{")) names.push(fallback[1]);
      for (const name of names) imports.set(name, match[2].slice(2));
    }

    const source = ts.createSourceFile(
      file.path,
      file.text,
      ts.ScriptTarget.Latest,
      true,
      ts.ScriptKind.TSX,
    );
    const visit = (node) => {
      if (isMapCall(node) && node.arguments.length > 0) {
        const callback = node.arguments[0];
        if (ts.isArrowFunction(callback) || ts.isFunctionExpression(callback)) {
          const names = derivedInside(
            callback.body,
            rowNames(callback.parameters[0]),
          );
          const scan = (inner) => {
            if (inner !== callback.body && isMapCall(inner)) return;
            if (
              ts.isJsxOpeningElement(inner) ||
              ts.isJsxSelfClosingElement(inner)
            ) {
              const tag = inner.tagName.getText(source);
              if (/^[A-Z]/.test(tag) && !CONTROL_TAGS.has(tag)) {
                const carriesRow = inner.attributes.properties.some(
                  (property) =>
                    ts.isJsxAttribute(property) &&
                    property.name.getText() !== "key" &&
                    property.initializer &&
                    mentions(property.initializer.getText(), names),
                );
                const specifier = imports.get(tag);
                if (carriesRow && specifier) {
                  for (const candidate of [
                    `${specifier}.tsx`,
                    `${specifier}/index.tsx`,
                  ]) {
                    if (
                      byPath.has(candidate) &&
                      /^modules\/[^/]+\/components\//.test(candidate)
                    ) {
                      out.add(candidate);
                    }
                  }
                }
              }
            }
            ts.forEachChild(inner, scan);
          };
          scan(callback.body);
        }
      }
      ts.forEachChild(node, visit);
    };
    visit(source);
  }
  return out;
}

function isControl(element, source) {
  const tag = element.tagName.getText(source);
  if (CONTROL_TAGS.has(tag)) return true;
  return Boolean(attribute(element, "onClick"));
}

const keyOf = (finding) => `${finding.file} :: ${finding.label}`;

function readBaseline() {
  return existsSync(BASELINE_PATH)
    ? JSON.parse(readFileSync(BASELINE_PATH, "utf8")).sites
    : {};
}

function runCli() {
  const quiet = process.argv.includes("--quiet");
  const baselineMode = process.argv.includes("--baseline");
  const writeBaseline = process.argv.includes("--write-baseline");

  const rels = walk(SRC)
    .map((file) => relative(SRC, file).split("\\").join("/"))
    .filter(isScanned);
  const corpus = rels.map((path) => ({
    path,
    text: readFileSync(resolve(SRC, path), "utf8"),
  }));
  const rowComponents = rowComponentPaths(corpus);
  const findings = corpus.flatMap((file) =>
    rowActionNamesIn(file.path, file.text, {
      whole: rowComponents.has(file.path),
    }),
  );

  if (writeBaseline) {
    const sites = {};
    for (const finding of findings) sites[keyOf(finding)] = 1;
    const body = {
      generatedBy: "node scripts/check-row-action-names.mjs --write-baseline",
      note:
        "Row actions whose accessible name is the same constant for every " +
        "row. One entry per file and name; a plain run fails on any entry the " +
        "tree no longer holds as well as on a new one, and --write-baseline " +
        "is the only writer.",
      sites,
    };
    writeFileSync(BASELINE_PATH, `${JSON.stringify(body, null, 2)}\n`);
    console.log(
      `row-action-baseline.json written: ${Object.keys(sites).length} entry(ies).`,
    );
    process.exit(0);
  }

  const frozen = readBaseline();
  const fresh = findings.filter((finding) => !frozen[keyOf(finding)]);
  const held = new Set(findings.map(keyOf));
  const paid = Object.keys(frozen).filter((key) => !held.has(key));

  const visible = baselineMode ? fresh : findings;
  if (visible.length > 0) {
    if (!quiet) {
      console.error(
        `\nrow-action-names: ${visible.length} row action(s) carry the same ` +
          `name on every row:\n`,
      );
      for (const finding of visible) {
        console.error(`  ${finding.file}:${finding.line} :: ${finding.label}`);
      }
      console.error(
        '\nPut the row in the accessible name — `aria-label={t("revokeNamed", ' +
          "{ name: key.name })}` or a visible label that names it.",
      );
    }
    process.exit(1);
  }

  if (baselineMode && paid.length > 0) {
    if (!quiet) {
      console.error(
        `\nrow-action-names: ${paid.length} baselined site(s) are fixed — ` +
          "drop them with --write-baseline so the ratchet only turns down:\n",
      );
      for (const key of paid) console.error(`  ${key}`);
    }
    process.exit(1);
  }

  if (!quiet) {
    console.log(
      `row-action-names: ${findings.length} finding(s) in ${rels.length} ` +
        "file(s) scanned.",
    );
  }
  process.exit(0);
}

if (
  process.argv[1] &&
  resolve(process.argv[1]) === fileURLToPath(import.meta.url)
) {
  runCli();
}
