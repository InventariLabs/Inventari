#!/usr/bin/env node
/**
 * check-query-error-read.mjs
 *
 * A failed load must not read as an answer.
 *
 * `const { data = [] } = useThings()` renders "no things" when the request
 * failed: the default is indistinguishable from a real empty list, so the
 * screen tells the user their stock is empty, their rules are gone or their
 * count is zero while the server was merely unreachable. The same holds for
 * `data?.total ?? 0` beside a query whose error nothing reads.
 *
 * The gate is literal. For every `const { … } = use<Something>(…)` (and
 * `const q = use<Something>(…)` read through `q.data`), a finding is a data
 * value that is given an empty default — in the pattern itself (`data = []`)
 * or at a use (`data?.items ?? []`, `data ?? 0`) — while the same pattern
 * never takes `isError`, `error`, `isLoadingError` or `status` and reads it.
 * A query read inline (`useThings().data ?? []`) binds no error at all, so
 * an empty default there is always a finding.
 * "Reads" means a use of the bound name in the same top-level declaration
 * (component or hook), outside string literals and other query patterns:
 * a sibling component, a prose mention or another hook's `isError` does not
 * count. Take `isError` in the pattern that destructures the data and use it.
 *
 * Two more shapes read the same question from the other end, because the
 * 2026-11 QA round met them on screens this rule called clean:
 *
 *   - A claim about the data rendered with no outcome beside it. The
 *     product list's export button said "Nothing to export: this list is
 *     empty" beside the load error, because `hasRows={total > 0}` was
 *     computed off a defaulted list. A quantity derived from the query and
 *     then compared is read here, and the expression that renders it — the
 *     JSX braces or the attribute value — has to name the error or the
 *     loading state, by its field name or by the name the read bound it to
 *     (`locationsLoading`). A name carries the query only through its own
 *     initializer (`const total = itemTotals(response)`); a `useState` beside
 *     a hook is not query data, nor is a mutation's result, and a name read
 *     through an object the query does not carry (`result.runs.length`) is
 *     not the query's either. The whole-query spelling (`const q =
 *     useItems()`) is a query only when the scope reads `q.data` or one of
 *     its outcome fields; a virtualizer or a router handle is a hook too, and
 *     a record's own `status` is not the read's. Two shapes answer for the claim below them, and both
 *     have to be in the component's own body: an `if (isError) return …` in
 *     it, whose following statements run only once the read has an answer;
 *     and the claim in the alternate branch of `isError ? … : <claim>`. A
 *     guard inside a click handler or an effect answers for nothing — it
 *     runs after the screen has drawn — and a ternary or an outcome word
 *     elsewhere in the JSX does not answer either: a claim beside
 *     `{isError ? <QueryFailure /> : null}` still renders while the read
 *     failed.
 *   - A component that models loading and not failure. The recipe picker's
 *     `SuggestedRecipes` took `suggestions` and `isLoading`, drew a spinner
 *     while loading, and answered "No suggestions for this slot" on a
 *     request that failed: it never received the failure its parent had.
 *   - A screen that reads `isLoading` over a list kept from the previous
 *     request. `keepPreviousData` swaps a search's results out while the
 *     next one runs, and `isLoading` is false by then — the equipment
 *     locations screen drew "No locations yet" over 38 of them, and its
 *     dashboard counted "8 assets need attention" before 9. An infinite
 *     query is one such list (`.pages`); `placeholderData: keepPreviousData`
 *     on an ordinary query is the other, and both are read here.
 *
 * Modes:
 *   node check-query-error-read.mjs                    # report and exit 1
 *   node check-query-error-read.mjs --baseline         # only NEW findings fail
 *   node check-query-error-read.mjs --write-baseline   # snapshot current
 *   node check-query-error-read.mjs --quiet            # exit code only
 *
 * Baseline: frontend/scripts/query-error-read-baseline.json (one entry per
 * file and site). The goal is an empty baseline.
 */
import { existsSync, readFileSync, readdirSync, writeFileSync } from "node:fs";
import { resolve, relative } from "node:path";
import { fileURLToPath } from "node:url";

import ts from "typescript";

import { blankComments } from "./source-text.mjs";

const ROOT = resolve(new URL("..", import.meta.url).pathname); // frontend/
const SRC = resolve(ROOT, "src");
const BASELINE_PATH = resolve(ROOT, "scripts/query-error-read-baseline.json");

const EMPTY_DEFAULT = String.raw`(?:\[\]|\{\}|0)(?![\w.])`;

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
  if (/(^|\/)(test|__tests__|types)\//.test(rel)) return false;
  return true;
}

/** Text of a balanced `{…}` starting at the `{` at `open`; null when unclosed. */
function braced(text, open) {
  let depth = 0;
  for (let i = open; i < text.length; i++) {
    if (text[i] === "{") depth++;
    else if (text[i] === "}" && --depth === 0) return text.slice(open + 1, i);
  }
  return null;
}

/**
 * Which characters are code, read from the TypeScript syntax tree: false in
 * comments, string and regular-expression literals, JSX text and the text
 * parts of a template literal; true in a template's `${…}` holes. A parser
 * knows where a quote opens a string and where it is an apostrophe in JSX
 * text, a regex or a comment, which a character scan cannot tell.
 */
function codeMask(text, rel) {
  const kind = /\.tsx$/.test(rel) ? ts.ScriptKind.TSX : ts.ScriptKind.TS;
  const tree = ts.createSourceFile(
    rel,
    text,
    ts.ScriptTarget.Latest,
    false,
    kind,
  );
  const mask = new Array(text.length).fill(true);
  const blank = (from, to) => mask.fill(false, from, to);
  const literal = new Set([
    ts.SyntaxKind.StringLiteral,
    ts.SyntaxKind.NoSubstitutionTemplateLiteral,
    ts.SyntaxKind.TemplateHead,
    ts.SyntaxKind.TemplateMiddle,
    ts.SyntaxKind.TemplateTail,
    ts.SyntaxKind.RegularExpressionLiteral,
    ts.SyntaxKind.JsxText,
  ]);
  const visit = (node) => {
    // Trivia before a node is whitespace and comments.
    blank(node.pos, node.getStart(tree));
    if (literal.has(node.kind)) blank(node.getStart(tree), node.end);
    else ts.forEachChild(node, visit);
  };
  visit(tree);
  blank(tree.endOfFileToken.pos, text.length);
  return mask;
}

/** Index of the `)` closing the `(` at `open`; -1 when unclosed. */
function closingParen(text, open, isCode) {
  let depth = 0;
  for (let i = open; i < text.length; i++) {
    if (!isCode[i]) continue;
    if (text[i] === "(") depth++;
    else if (text[i] === ")" && --depth === 0) return i;
  }
  return -1;
}

/** The name `data` is bound to in a destructuring body, and its default. */
function dataBinding(body) {
  const m = body.match(
    new RegExp(
      String.raw`(?:^|[,\s])data\s*(?::\s*(\w+))?\s*(=\s*${EMPTY_DEFAULT})?`,
    ),
  );
  if (!m) return null;
  return { alias: m[1] ?? "data", defaulted: Boolean(m[2]) };
}

/**
 * The top-level declaration (component, hook, helper) holding `index`:
 * prettier puts every one at column 0. Falls back to the whole file.
 */
function scopeOf(text, index) {
  const decl =
    /^(?:export\s+)?(?:default\s+)?(?:async\s+)?(?:function\s*\*?\s*(\w+)|const\s+(\w+)\s*(?::[^=\n]+)?=\s*(?:async\s+)?(?:\(|function\b|\w+\s*=>|(?:React\.)?(?:memo|forwardRef)\())/gm;
  let start = 0;
  let end = text.length;
  let name = "<module>";
  let m;
  while ((m = decl.exec(text)) !== null) {
    if (m.index <= index) {
      start = m.index;
      name = m[1] ?? m[2];
    } else {
      end = m.index;
      break;
    }
  }
  return { start, end, name };
}

/** Scope text with string literals and every query pattern blanked out. */
function readableScope(text, scope) {
  return text
    .slice(scope.start, scope.end)
    .replace(/"(?:[^"\\\n]|\\.)*"|'(?:[^'\\\n]|\\.)*'/g, '""')
    .replace(/`[^`]*`/g, (t) =>
      t.replace(/\$\{([^}]*)\}|[^$`]+|\$/g, (m, hole) =>
        hole === undefined ? "" : m,
      ),
    )
    .replace(
      /\bconst\s*\{[^;]*?\}\s*(?::[^=;]+)?=\s*(?:\(\s*)?use[A-Z]/g,
      "use",
    );
}

/**
 * Whether an error binding taken in the destructuring is used afterwards:
 * naming `isError` in the pattern is not reading it. `rest` is the readable
 * text of the enclosing declaration.
 */
function errorIsRead(body, rest) {
  const taken = body.replace(/\bdata\b\s*(?::\s*\w+)?/, "");
  const names = /\b(isError|error|isLoadingError|status)\b(?:\s*:\s*(\w+))?/g;
  for (const m of taken.matchAll(names)) {
    const local = m[2] ?? m[1];
    if (new RegExp(String.raw`(?<![.\w])${local}\b`).test(rest)) return true;
  }
  return false;
}

export function unreadErrorsIn(rel, source) {
  const text = blankComments(source);
  const out = [];
  const lineOf = (index) => text.slice(0, index).split("\n").length;

  const pattern = /\bconst\s*\{/g;
  let match;
  while ((match = pattern.exec(text)) !== null) {
    const open = match.index + match[0].length - 1;
    const body = braced(text, open);
    if (body === null) continue;
    const after = text.slice(open + body.length + 2);
    if (!/^\s*(?::[^=]+)?=\s*(?:\(\s*)?use[A-Z]\w*\s*[(<]/.test(after))
      continue;
    const data = dataBinding(body);
    if (!data) continue;
    const scope = scopeOf(text, match.index);
    if (errorIsRead(body, readableScope(text, scope))) continue;
    const alias = data.alias;
    const atUse = new RegExp(
      String.raw`\b${alias}\s*(?:\?\.[\w.?]+|\.[\w.]+)?\s*\?\?\s*${EMPTY_DEFAULT}`,
    ).test(text.slice(scope.start, scope.end));
    if (data.defaulted || atUse) {
      const hook = after.match(/use[A-Z]\w*/)[0];
      out.push({
        file: rel,
        line: lineOf(match.index),
        site: `${scope.name} :: ${hook} ${body.replace(/\s+/g, " ").trim()}`,
      });
    }
  }

  const whole = /\bconst\s+(\w+)\s*=\s*use[A-Z]\w*\s*[(<]/g;
  while ((match = whole.exec(text)) !== null) {
    const name = match[1];
    const scope = scopeOf(text, match.index);
    const scoped = readableScope(text, scope);
    const atUse = new RegExp(
      String.raw`\b${name}\.data\b[\w.?]*\s*\?\?\s*${EMPTY_DEFAULT}`,
    ).test(scoped);
    const reads = new RegExp(
      String.raw`\b${name}\.(isError|error|isLoadingError|status)\b`,
    ).test(scoped);
    if (atUse && !reads) {
      out.push({
        file: rel,
        line: lineOf(match.index),
        site: `${scope.name} :: ${name} = ${match[0].match(/use[A-Z]\w*/)[0]}`,
      });
    }
  }

  const isCode = codeMask(source, rel);
  const inline = /\buse[A-Z]\w*\s*(?:<[^>()]*>\s*)?\(/g;
  while ((match = inline.exec(source)) !== null) {
    if (!isCode[match.index]) continue;
    const close = closingParen(
      source,
      match.index + match[0].length - 1,
      isCode,
    );
    if (close === -1) continue;
    const read = new RegExp(
      String.raw`^\s*\.data\b(?:\??\.\w+)*\s*\?\?\s*${EMPTY_DEFAULT}`,
    );
    if (!read.test(text.slice(close + 1))) continue;
    const scope = scopeOf(text, match.index);
    out.push({
      file: rel,
      line: lineOf(match.index),
      site: `${scope.name} :: ${match[0].match(/use[A-Z]\w*/)[0]}().data`,
    });
  }
  return out;
}

/** The initializer expression starting at `from`, to its `;` or scope end. */
function initializerAt(slice, from) {
  let depth = 0;
  for (let i = from; i < slice.length; i++) {
    const char = slice[i];
    if (char === "(" || char === "[" || char === "{") depth++;
    else if (char === ")" || char === "]" || char === "}") {
      if (depth === 0) return slice.slice(from, i);
      depth--;
    } else if (char === ";" && depth === 0) {
      return slice.slice(from, i);
    }
  }
  return slice.slice(from);
}

/**
 * The identifier names a destructured pattern binds, and their locals.
 */
function boundNames(body) {
  const names = [];
  for (const part of body.split(",")) {
    const [left, alias] = part.split(":").map((piece) => piece.trim());
    const name = (alias ?? left).split("=")[0].trim();
    if (/^[A-Za-z_$][\w$]*$/.test(name)) names.push(name);
  }
  return names;
}

/**
 * Names in the scope whose value comes from the query: `const items = …data`
 * and `const { total } = itemTotals(itemsResponse)` both carry it, and the
 * screen's claim is written against them. Only a declaration's own
 * initializer carries it: a `useState` array or a mutation's result beside a
 * query is not that query's data.
 */
function derivedNames(text, scope, seeds) {
  const derived = new Set(seeds);
  const slice = text.slice(scope.start, scope.end);
  const declaration =
    /(?:const|let)\s+(?:\{([^}]*)\}|\[([^\]]*)\]|([A-Za-z_$][\w$]*))\s*(?::[^=;\n]+)?=\s*/g;
  for (let pass = 0; pass < 3; pass++) {
    let grew = false;
    for (const match of slice.matchAll(declaration)) {
      const rhs = initializerAt(slice, match.index + match[0].length);
      const bound = boundNames(match[1] ?? match[2] ?? match[3] ?? "");
      if (bound.length === 0) continue;
      if (bound.some((name) => derived.has(name))) continue;
      const names = [...derived];
      if (names.some((name) => new RegExp(String.raw`\b${name}\b`).test(rhs))) {
        for (const name of bound) {
          derived.add(name);
          grew = true;
        }
      }
    }
    if (!grew) break;
  }
  return [...derived];
}

/** The JSX expression or attribute value around an offset. */
function renderedExpression(text, index) {
  let depth = 0;
  let start = -1;
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
  if (start === -1) return null;
  depth = 0;
  for (let i = start; i < text.length; i++) {
    if (text[i] === "{") depth++;
    else if (text[i] === "}" && --depth === 0) {
      return text.slice(start, i + 1);
    }
  }
  return null;
}

const OUTCOME =
  /\b(?:isError|error|isLoadingError|status|isLoading|isPending|isFetching|isPlaceholderData|failed)\b/;

/** `name` as a whole word in `text`; the names are identifiers. */
function mentions(text, name) {
  return new RegExp(String.raw`\b${name.replace(/\$/g, "\\$")}\b`).test(text);
}

/**
 * A test read positively. `if (!isError) return <List />` returns on
 * success and leaves the claim below it to render while the read failed, so
 * a negated flag answers for nothing. `outcomes` holds the names the read
 * bound its outcome to — `isTreeLoading`, `locationsFailed` — which the
 * fixed list of field names does not spell.
 */
function readsOutcome(test, outcomes) {
  const positive = test.replace(/!\s*[\w$]+(?:\.[\w$]+)*/g, "");
  return (
    OUTCOME.test(positive) || outcomes.some((name) => mentions(positive, name))
  );
}

/** Whether a statement cannot complete: it returns or throws, itself or last. */
function alwaysExits(statement) {
  if (!statement) return false;
  if (ts.isReturnStatement(statement) || ts.isThrowStatement(statement)) {
    return true;
  }
  if (ts.isBlock(statement)) {
    return alwaysExits(statement.statements[statement.statements.length - 1]);
  }
  return false;
}

/** The deepest node of `tree` that holds `at`. */
function nodeAt(tree, at) {
  let node = tree;
  for (;;) {
    let next = null;
    ts.forEachChild(node, (child) => {
      if (child.getStart(tree) <= at && at < child.end) {
        next = child;
        return true;
      }
      return false;
    });
    if (!next) return node;
    node = next;
  }
}

/**
 * The component, hook or helper declaration the scope names, when the syntax
 * tree has one. `memo(…)` and `forwardRef(…)` hold it as their argument.
 */
function scopeFunctionAt(tree, start) {
  for (const statement of tree.statements) {
    if (statement.getStart(tree) !== start) continue;
    if (ts.isFunctionDeclaration(statement)) return statement;
    if (!ts.isVariableStatement(statement)) return null;
    for (const declaration of statement.declarationList.declarations) {
      let init = declaration.initializer;
      if (init && ts.isCallExpression(init) && init.arguments.length > 0) {
        init = init.arguments[0];
      }
      if (init && (ts.isArrowFunction(init) || ts.isFunctionExpression(init))) {
        return init;
      }
    }
    return null;
  }
  return null;
}

/** Whether `block` belongs to the component's own body, not a nested function. */
function ownedBy(block, scopeFunction) {
  if (!scopeFunction) return false;
  for (let node = block.parent; node; node = node.parent) {
    if (ts.isFunctionLike(node)) return node === scopeFunction;
  }
  return false;
}

/**
 * Whether the claim at `at` cannot render before the read has an answer.
 *
 * Two shapes answer for it, and both have to be in the component's own
 * body: `if (isError) return <QueryFailure />`, whose remaining statements
 * run only once the read has answered; and the claim in the alternate
 * branch of `isError ? <QueryFailure /> : <Button disabled={rows.length === 0}>`.
 * A guard inside a click handler or an effect answers for nothing — it runs
 * after the screen has drawn — and a ternary or an outcome word elsewhere
 * in the JSX does not either: `{isError ? <QueryFailure /> : null}` beside
 * `hasRows={total > 0}` draws the claim while the read failed.
 */
function earlyOutcome(tree, scopeFunction, at, outcomes) {
  const leaf = nodeAt(tree, at);
  let node = leaf;
  while (node && node !== scopeFunction) {
    const parent = node.parent;
    if (!parent) break;
    if (ts.isConditionalExpression(parent)) {
      const alternate = parent.whenFalse;
      if (
        at >= alternate.getStart(tree) &&
        at < alternate.end &&
        readsOutcome(parent.condition.getText(tree), outcomes)
      ) {
        return true;
      }
    }
    if (ts.isBlock(parent) && ownedBy(parent, scopeFunction)) {
      for (const statement of parent.statements) {
        if (statement.end > at) break;
        if (
          ts.isIfStatement(statement) &&
          alwaysExits(statement.thenStatement) &&
          readsOutcome(statement.expression.getText(tree), outcomes)
        ) {
          return true;
        }
      }
    }
    node = parent;
  }
  return false;
}

/**
 * Findings for the claims `derived` makes in one scope: a length or a
 * zero-comparison that decides an empty state or a disabled action.
 * `outcomes` are the names the read bound its outcome to; `answersEarly`
 * says whether the component has already answered with that outcome above
 * the claim.
 */
function claimFindings(
  rel,
  text,
  scope,
  derived,
  outcomes,
  lineOf,
  answersEarly,
) {
  const out = [];
  if (derived.length === 0) return out;
  const names = derived.map((n) => n.replace(/\$/g, "\\$")).join("|");
  const claims = new RegExp(
    String.raw`\b(?:${names})\b\s*\.\s*length\b|\b(?:${names})\b\s*(?:>=?|<=?|===?|!==?)\s*0\b`,
    "g",
  );
  for (const claim of text.slice(scope.start, scope.end).matchAll(claims)) {
    const at = scope.start + claim.index;
    // A name reached through an object the query does not carry is not the
    // query's data: `result.runs.length` reads a mutation's result beside
    // the `runs` query, and its count is not a claim about the read.
    const owner = /([A-Za-z_$][\w$]*)\s*\??\.\s*$/.exec(
      text.slice(scope.start, at),
    );
    if (owner && !derived.includes(owner[1])) continue;
    const plain = claim[0].replace(/\s+/g, "");
    const comparison = !/\.length$/.test(plain);
    if (
      comparison &&
      !/(count|total|rows|items|list|records|entries|results)/i.test(plain)
    ) {
      continue;
    }
    const rendered = renderedExpression(text, at);
    const expression =
      rendered ??
      text
        .slice(Math.max(0, text.lastIndexOf("return", at)), at + 400)
        .split(";")[0];
    if (
      OUTCOME.test(expression) ||
      outcomes.some((name) => mentions(expression, name))
    ) {
      continue;
    }
    if (answersEarly(scope, at, outcomes)) continue;
    const before = text.slice(Math.max(0, at - 80), at);
    // The claims that lie are the ones deciding emptiness, a disabled action,
    // or a count in a sentence: an ordinary ".length" in a list header says
    // how many records there are, and while one page loads the number is on
    // its way with it — the screens that read it as zero are the ones that
    // decide the empty state or block the action.
    const decides =
      /(?:has|is|show)[A-Z]\w*=\{\s*[\w?.]*$/.test(before) ||
      /\bdisabled=\{\s*[^}]*$/.test(before) ||
      /<EmptyState\b/.test(expression) ||
      /\bcount\s*:/.test(expression);
    if (!decides) continue;
    out.push({
      file: rel,
      line: lineOf(at),
      site: `${scope.name} :: ${claim[0].replace(/\s+/g, "")}`,
    });
  }
  return out;
}

/** Claims about a query's data rendered with no outcome in the expression. */
export function unguardedClaimsIn(rel, source) {
  const text = blankComments(source);
  const out = [];
  const lineOf = (index) => text.slice(0, index).split("\n").length;
  // The syntax tree is built once, and only when a claim needs it: the text
  // scan narrows the file to the few places that ask a question about data.
  let tree = null;
  const scopes = new Map();
  const answersEarly = (scope, at, outcomes) => {
    tree ??= ts.createSourceFile(
      rel,
      text,
      ts.ScriptTarget.Latest,
      true,
      /\.tsx$/.test(rel) ? ts.ScriptKind.TSX : ts.ScriptKind.TS,
    );
    if (!scopes.has(scope.start)) {
      scopes.set(scope.start, scopeFunctionAt(tree, scope.start));
    }
    return earlyOutcome(tree, scopes.get(scope.start), at, outcomes);
  };
  const pattern = /\bconst\s*\{/g;
  let match;
  while ((match = pattern.exec(text)) !== null) {
    const open = match.index + match[0].length - 1;
    const body = braced(text, open);
    if (body === null) continue;
    const after = text.slice(open + body.length + 2);
    if (!/^\s*(?::[^=]+)?=\s*(?:\(\s*)?use[A-Z]\w*\s*[(<]/.test(after))
      continue;
    const data = dataBinding(body);
    if (!data) continue;
    const scope = scopeOf(text, match.index);
    const seeds = [
      data.alias,
      ...boundNames(body).filter((name) =>
        /Error|error|Loading|Pending|Fetching|status|Placeholder|Failed|failed|Failure|failure/.test(
          name,
        ),
      ),
    ];
    const outcomes = seeds.slice(1).filter((name) => name !== data.alias);
    out.push(
      ...claimFindings(
        rel,
        text,
        scope,
        derivedNames(text, scope, seeds),
        outcomes,
        lineOf,
        answersEarly,
      ),
    );
  }
  // The whole-query variable (`const listQuery = useItems(…)`) is the other
  // spelling, and the page then builds its count out of `listQuery.data`.
  const whole = /\bconst\s+([A-Za-z_$][\w$]*)\s*=\s*use[A-Z]\w*\s*[(<]/g;
  while ((match = whole.exec(text)) !== null) {
    const name = match[1];
    const scope = scopeOf(text, match.index);
    // Only a hook read through the query's own fields is a query: a
    // virtualizer or a router handle is a hook too, and its methods are not
    // data whose failure the screen has to answer for. A `status` the hook
    // returns is often the record's own — a document's, a job's — not the
    // read's, so reading one does not make the hook a query.
    const readsQuery = new RegExp(
      String.raw`\b${name}\.(?:data|error|refetch|isLoading|isLoadingError|isPending|isFetching|isPlaceholderData)\b`,
    ).test(text.slice(scope.start, scope.end));
    if (!readsQuery) continue;
    const derived = derivedNames(text, scope, [name]);
    out.push(
      ...claimFindings(rel, text, scope, derived, [], lineOf, answersEarly),
    );
  }
  return out;
}

const LIST_PROP =
  /^(?:items|rows|list|entries|options|suggestions|records|results|plans|keys|locations|assets|tags|members|stages|lines|logs|events|things|data|values|children)$/i;
const LOADING_PROP = /^(?:isLoading|loading|isPending|isFetching)$/;
const FAILURE_PROP = /(?:isError|error|failed|failure)/i;

/**
 * Components that model the loading of a list and not its failure.
 *
 * A spinner for "still coming" and an empty state for "nothing here" leaves
 * the third outcome nowhere to go: a failed request lands in the empty state
 * and reads as an answer. The parent usually holds the error — the picker
 * did — and does not hand it down, so the child cannot say what happened.
 */
export function loadingWithoutFailureIn(rel, source) {
  if (!/\.tsx$/.test(rel)) return [];
  if (!/^modules\//.test(rel)) return [];
  const out = [];
  const kind = ts.ScriptKind.TSX;
  const tree = ts.createSourceFile(
    rel,
    source,
    ts.ScriptTarget.Latest,
    true,
    kind,
  );
  const lineOf = (node) =>
    tree.getLineAndCharacterOfPosition(node.getStart()).line + 1;

  const propTypes = new Map();
  const eachNode = (node, visit) => {
    visit(node);
    ts.forEachChild(node, (child) => eachNode(child, visit));
  };
  eachNode(tree, (node) => {
    if (ts.isInterfaceDeclaration(node) && node.name.text.endsWith("Props")) {
      for (const member of node.members) {
        if (
          ts.isPropertySignature(member) &&
          member.name &&
          ts.isIdentifier(member.name) &&
          member.type
        ) {
          propTypes.set(member.name.text, member.type.getText(tree));
        }
      }
    }
  });

  eachNode(tree, (node) => {
    const fn =
      ts.isFunctionDeclaration(node) &&
      node.name &&
      /^[A-Z]/.test(node.name.text)
        ? node
        : ts.isFunctionExpression(node) &&
            node.name &&
            /^[A-Z]/.test(node.name.text)
          ? node
          : null;
    if (!fn || !fn.parameters[0]) return;
    const parameter = fn.parameters[0];
    if (!ts.isObjectBindingPattern(parameter.name)) return;
    const props = parameter.name.elements
      .map((element) =>
        ts.isIdentifier(element.name) ? element.name.text : null,
      )
      .filter(Boolean);
    const loading = props.find((name) => LOADING_PROP.test(name));
    if (!loading) return;
    if (props.some((name) => FAILURE_PROP.test(name))) return;
    const lists = props.filter(
      (name) =>
        LIST_PROP.test(name) || /\[\]|Array</.test(propTypes.get(name) ?? ""),
    );
    if (lists.length === 0) return;
    const body = fn.body?.getText(tree) ?? "";
    for (const list of lists) {
      const claim = new RegExp(
        String.raw`(?:!\s*${list}\s*\.\s*length|\b${list}\s*\.\s*length\s*(?:===?|>=?)\s*0)`,
      );
      if (claim.test(body)) {
        out.push({
          file: rel,
          line: lineOf(fn),
          site: `${fn.name.text} :: ${list} with ${loading} but no failure prop`,
        });
        break;
      }
    }
  });
  return out;
}

/**
 * A screen that reads `isLoading` for a list kept from the last request.
 *
 * `placeholderData: keepPreviousData` swaps the list out while the next page
 * of a search arrives, and `isLoading` is only true before the first one — so
 * a screen that guards its empty state with it alone says "no locations yet"
 * over data that is on its way. The equipment locations screen was read that
 * way at 38 locations. `isFetching` and `isPlaceholderData` are the flags
 * that cover the second request.
 *
 * An infinite query (`.pages`) and an ordinary query with `keepPreviousData`
 * both keep the previous list on screen; both are read here.
 */
export function pagedEmptyIn(rel, source) {
  const text = blankComments(source);
  if (/\b(?:isPlaceholderData|isFetching)\b/.test(text)) return [];
  const keepsPrevious =
    /\bkeepPreviousData\b/.test(text) ||
    /\.pages\b/.test(text) ||
    /\bpages\s*\?/.test(text);
  if (!keepsPrevious) return [];
  const empty = /<EmptyState\b/.exec(text);
  if (!empty) return [];
  return [
    {
      file: rel,
      line: text.slice(0, empty.index).split("\n").length,
      site: `${scopeOf(text, empty.index).name} :: paged list empty state without isPlaceholderData`,
    },
  ];
}

function main() {
  const args = process.argv.slice(2);
  const quiet = args.includes("--quiet");
  const baselineMode = args.includes("--baseline");
  const writeBaseline = args.includes("--write-baseline");

  const files = walk(SRC)
    .map((f) => relative(SRC, f).split("\\").join("/"))
    .filter(isScanned);
  const findings = [
    ...new Map(
      files
        .flatMap((rel) => {
          const source = readFileSync(resolve(SRC, rel), "utf8");
          return [
            ...unreadErrorsIn(rel, source),
            ...unguardedClaimsIn(rel, source),
            ...loadingWithoutFailureIn(rel, source),
            ...pagedEmptyIn(rel, source),
          ];
        })
        .map((finding) => [`${finding.file} :: ${finding.site}`, finding]),
    ).values(),
  ];

  const keyOf = (finding) => `${finding.file} :: ${finding.site}`;

  if (writeBaseline) {
    const sites = {};
    for (const finding of findings) sites[keyOf(finding)] = 1;
    const body = {
      generatedBy: "node scripts/check-query-error-read.mjs --write-baseline",
      note:
        "Failed or still-loading reads rendered as answers. One entry per " +
        "file and site; a plain run fails on any entry the tree no longer " +
        "holds as well as on a new one, and --write-baseline is the only " +
        "writer.",
      sites,
    };
    writeFileSync(BASELINE_PATH, `${JSON.stringify(body, null, 2)}\n`);
    console.log(
      `query-error-read-baseline.json written: ${Object.keys(sites).length} ` +
        "site(s).",
    );
    process.exit(0);
  }

  const frozen = existsSync(BASELINE_PATH)
    ? JSON.parse(readFileSync(BASELINE_PATH, "utf8")).sites
    : {};
  const fresh = findings.filter((finding) => !frozen[keyOf(finding)]);
  const held = new Set(findings.map(keyOf));
  const paid = Object.keys(frozen).filter((key) => !held.has(key));

  const visible = baselineMode ? fresh : findings;
  if (visible.length > 0) {
    if (!quiet) {
      console.error(
        `\nquery-error-read: ${visible.length} failed or loading read ` +
          "rendered as an answer:\n",
      );
      for (const f of visible) {
        console.error(`  ${f.file}:${f.line} :: ${f.site}`);
      }
      console.error(
        "\nA query's empty default renders as an answer when the request " +
          "failed or is still loading. Read `isError` and `isLoading` and " +
          "show the failed or loading state instead of the empty one; a " +
          "child that draws the empty state takes the failure as a prop.",
      );
    }
    process.exit(1);
  }

  if (baselineMode && paid.length > 0) {
    if (!quiet) {
      console.error(
        `\nquery-error-read: ${paid.length} baselined site(s) are fixed — ` +
          "drop them with --write-baseline so the ratchet only turns down:\n",
      );
      for (const key of paid) console.error(`  ${key}`);
    }
    process.exit(1);
  }

  if (!quiet) {
    console.log(
      `query-error-read: ${files.length} file(s) scanned, ` +
        `${findings.length} finding(s)` +
        `${baselineMode ? ", all held by the baseline" : ""}.`,
    );
  }
  process.exit(0);
}

if (
  process.argv[1] &&
  resolve(process.argv[1]) === fileURLToPath(import.meta.url)
) {
  main();
}
