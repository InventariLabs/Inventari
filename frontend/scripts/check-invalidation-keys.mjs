/**
 * check-invalidation-keys.mjs
 *
 * Every query key — the one a query reads with and the one a mutation
 * invalidates — comes from `hooks/queries/keys.ts`.
 *
 * React Query matches invalidations by prefix, and a prefix that matches
 * nothing fails silently: the mutation looks like it refreshes the screen,
 * the screen keeps its stale data, and nothing anywhere says so. The
 * application has been here twice — `["stats-overview"]`, invalidated three
 * times against a cache entry nothing ever wrote, and `["valuation"]`, which
 * no query in this tree has ever used.
 *
 * The invariant, checked on the TypeScript AST (so a multi-line key, a
 * spread, a `.concat` and a conditional are all seen):
 *
 *   the value of every `queryKey:` property, and of the key handed to
 *   `invalidateQueries`, is rooted at `queryKeys` — directly, through a
 *   spread, a call, a property chain, a `const` in the same file that is
 *   itself rooted there, or either branch of a conditional.
 *
 * Anything else is a finding of one of two kinds:
 *   - a *literal* array of strings (`["ghost"]`) — never tolerated, and its
 *     first segment is also checked against the registry's roots;
 *   - a *foreign root* — a key held in a variable, a prop, or a local
 *     mini-registry (`const sabKeys = { all: [...] }`). The registry cannot
 *     check what such a key says, so each file that still has one is listed
 *     in `invalidation-keys-baseline.json` with a count, a reason, an owner
 *     and an expiry. The count may only fall; raising it, or adding a file,
 *     is `--write-baseline` plus a reason written by hand. A local registry
 *     never widens the set of roots a key is checked against.
 *
 * Modes:
 *   node check-invalidation-keys.mjs            # report and exit 1 on findings
 *   node check-invalidation-keys.mjs --quiet    # exit code only
 *   node check-invalidation-keys.mjs --write-baseline
 */
import { readFileSync, readdirSync, writeFileSync } from "node:fs";
import { resolve, relative } from "node:path";
import { fileURLToPath } from "node:url";
import ts from "typescript";

const ROOT = resolve(new URL("..", import.meta.url).pathname); // frontend/
const SRC = resolve(ROOT, "src");
const KEYS_FILE = resolve(SRC, "hooks/queries/keys.ts");
const BASELINE = resolve(ROOT, "scripts/invalidation-keys-baseline.json");
const REGISTRY = "queryKeys";

function walk(dir, out = []) {
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const full = resolve(dir, entry.name);
    if (entry.isDirectory()) walk(full, out);
    else out.push(full);
  }
  return out;
}

function isScanned(rel) {
  if (!/\.(ts|tsx)$/.test(rel)) return false;
  if (/\.test\.(ts|tsx)$/.test(rel)) return false;
  if (rel === "src/hooks/queries/keys.ts") return false;
  return true;
}

/** Every first segment a registered key can start with. */
export function registeredRoots(keysSource) {
  const roots = new Set();
  for (const match of keysSource.matchAll(/\[\s*"([^"]+)"/g)) {
    roots.add(match[1]);
  }
  return roots;
}

/** Peel the wrappers that do not change which registry a key comes from. */
function unwrap(node) {
  while (
    ts.isAsExpression(node) ||
    ts.isParenthesizedExpression(node) ||
    ts.isNonNullExpression(node) ||
    ts.isSatisfiesExpression(node)
  ) {
    node = node.expression;
  }
  return node;
}

/** Same-file `const name = <init>` declarations, to follow `const k = queryKeys…`. */
function constInitializers(sf) {
  const map = new Map();
  (function visit(node) {
    if (
      ts.isVariableDeclaration(node) &&
      ts.isIdentifier(node.name) &&
      node.initializer &&
      node.parent.flags & ts.NodeFlags.Const
    ) {
      map.set(node.name.text, node.initializer);
    }
    ts.forEachChild(node, visit);
  })(sf);
  return map;
}

/** Classify a key expression: `[{ kind: "ok" } | { kind: "literal", root }
 * | { kind: "foreign", root }]` — a list because a conditional has two ways. */
function classify(node, consts, depth = 0) {
  node = unwrap(node);
  if (ts.isConditionalExpression(node)) {
    return [
      ...classify(node.whenTrue, consts, depth),
      ...classify(node.whenFalse, consts, depth),
    ];
  }
  if (ts.isArrayLiteralExpression(node)) {
    const first = node.elements[0];
    if (!first) return [{ kind: "literal", root: "" }];
    if (ts.isSpreadElement(first)) return classify(first.expression, consts, depth);
    if (ts.isStringLiteralLike(first)) return [{ kind: "literal", root: first.text }];
    return [{ kind: "foreign", root: first.getText() }];
  }
  if (
    ts.isPropertyAccessExpression(node) ||
    ts.isElementAccessExpression(node) ||
    ts.isCallExpression(node)
  ) {
    return classify(node.expression, consts, depth);
  }
  if (ts.isIdentifier(node)) {
    // A file-local `const queryKeys = …` is a mini-registry, not the import.
    if (node.text === REGISTRY && !consts.has(REGISTRY)) return [{ kind: "ok" }];
    const init = consts.get(node.text);
    if (init && depth < 4) {
      const inner = classify(init, consts, depth + 1);
      // Only a key *derived from the registry* is followed; a local object of
      // arrays is a mini-registry and stays a foreign root under its own name.
      if (inner.every((r) => r.kind === "ok")) return inner;
    }
    return [{ kind: "foreign", root: node.text }];
  }
  return [{ kind: "foreign", root: ts.SyntaxKind[node.kind] }];
}

/** Every key expression in a file: `queryKey:` properties, the shorthand
 * `{ queryKey }`, and what `invalidateQueries` is called with when that is
 * not an object literal. Each carries what it is and where it sits. */
export function keyFindings(text, fileName = "file.tsx") {
  const sf = ts.createSourceFile(fileName, text, ts.ScriptTarget.Latest, true);
  const consts = constInitializers(sf);
  const findings = [];
  const add = (node, invalidating, results) => {
    const line = sf.getLineAndCharacterOfPosition(node.getStart()).line + 1;
    for (const r of results) findings.push({ ...r, invalidating, line });
  };
  (function visit(node) {
    if (ts.isPropertyAssignment(node) && node.name.getText() === "queryKey") {
      add(node, isInvalidation(node), classify(node.initializer, consts));
    } else if (
      ts.isShorthandPropertyAssignment(node) &&
      node.name.text === "queryKey"
    ) {
      add(node, isInvalidation(node), [{ kind: "foreign", root: "queryKey" }]);
    } else if (
      ts.isCallExpression(node) &&
      callName(node) === "invalidateQueries" &&
      node.arguments.length > 0 &&
      !ts.isObjectLiteralExpression(unwrap(node.arguments[0]))
    ) {
      add(node, true, [{ kind: "foreign", root: node.arguments[0].getText() }]);
    }
    ts.forEachChild(node, visit);
  })(sf);
  return findings;
}

function callName(call) {
  const callee = call.expression;
  if (ts.isPropertyAccessExpression(callee)) return callee.name.text;
  return ts.isIdentifier(callee) ? callee.text : "";
}

/** Is this `queryKey` property inside the argument of `invalidateQueries`? */
function isInvalidation(node) {
  const object = node.parent;
  const call = object?.parent;
  return Boolean(
    call && ts.isCallExpression(call) && callName(call) === "invalidateQueries",
  );
}

/** The failures a run produces: what the tree holds, against what the
 * baseline tolerates. Pure, so the rules can be exercised without a tree. */
export function invalidationKeyFailures({
  literals,
  foreign,
  phantoms,
  baseline,
  today = new Date().toISOString().slice(0, 10),
}) {
  const failures = [];
  if (phantoms.length > 0) {
    failures.push(
      `${phantoms.length} invalidation key(s) match no registered query:\n` +
        phantoms.map((p) => `  ${p}`).join("\n") +
        "\n  React Query matches by prefix, so this invalidates nothing and " +
        "says nothing. Point it at a key from hooks/queries/keys.ts.",
    );
  }
  if (literals.length > 0) {
    failures.push(
      `${literals.length} literal key(s) spelled out at a call site:\n` +
        literals.map((l) => `  ${l}`).join("\n") +
        "\n  A key written here is a key the registry cannot check — add it " +
        "to hooks/queries/keys.ts and use it from there.",
    );
  }
  const byFile = new Map();
  for (const entry of foreign) {
    const list = byFile.get(entry.file) ?? [];
    list.push(entry);
    byFile.set(entry.file, list);
  }
  const allowed = new Map((baseline.exceptions ?? []).map((e) => [e.file, e]));
  for (const [file, entries] of byFile) {
    const exception = allowed.get(file);
    const where = entries.map((e) => `${file}:${e.line} (${e.root})`).join(", ");
    if (!exception) {
      failures.push(
        `key(s) not rooted at ${REGISTRY}: ${where}. A key held in a variable ` +
          "or a local registry is invisible to the registry — build it from " +
          "hooks/queries/keys.ts.",
      );
    } else if (entries.length !== exception.count) {
      failures.push(
        `${file} has ${entries.length} key(s) not rooted at ${REGISTRY}, ` +
          `baseline ${exception.count}: ${where}. Fix the count in the ` +
          "baseline (a fall is progress; a rise needs a reason).",
      );
    }
  }
  for (const exception of baseline.exceptions ?? []) {
    if (!byFile.has(exception.file)) {
      failures.push(
        `baseline entry ${exception.file} no longer matches any foreign key — remove it.`,
      );
    }
  }
  for (const exception of baseline.exceptions ?? []) {
    for (const field of ["reason", "owner", "expiry"]) {
      if (!exception[field]) {
        failures.push(`baseline entry ${exception.file} has no ${field}.`);
      }
    }
    if (exception.expiry && exception.expiry < today) {
      failures.push(
        `baseline entry ${exception.file} expired on ${exception.expiry} — ` +
          "pay it off or renew it with a reason.",
      );
    }
  }
  return failures;
}

function main() {
  const roots = registeredRoots(readFileSync(KEYS_FILE, "utf8"));
  const files = walk(SRC).filter((f) =>
    isScanned(relative(ROOT, f).replaceAll("\\", "/")),
  );

  const phantoms = [];
  const literals = [];
  const foreign = [];
  for (const file of files) {
    const rel = relative(ROOT, file).replaceAll("\\", "/");
    const text = readFileSync(file, "utf8");
    if (!/queryKey|invalidateQueries/.test(text)) continue;
    for (const f of keyFindings(text, file)) {
      if (f.kind === "literal") {
        literals.push(`${rel}:${f.line} ["${f.root}", …]`);
        if (f.invalidating && !roots.has(f.root)) {
          phantoms.push(`${rel}:${f.line} ["${f.root}", …]`);
        }
      } else if (f.kind === "foreign") {
        foreign.push({ file: rel, line: f.line, root: f.root });
      }
    }
  }

  if (process.argv.includes("--write-baseline")) {
    let previous = { exceptions: [] };
    try {
      previous = JSON.parse(readFileSync(BASELINE, "utf8"));
    } catch {
      // first run
    }
    const known = new Map((previous.exceptions ?? []).map((e) => [e.file, e]));
    const counts = new Map();
    for (const f of foreign) counts.set(f.file, (counts.get(f.file) ?? 0) + 1);
    const exceptions = [...counts]
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([file, count]) => ({
        file,
        count,
        reason: known.get(file)?.reason ?? "",
        owner: known.get(file)?.owner ?? "",
        expiry: known.get(file)?.expiry ?? "",
      }));
    writeFileSync(BASELINE, `${JSON.stringify({ exceptions }, null, 2)}\n`);
    console.log(
      `invalidation-keys: baseline written (${exceptions.length} file(s)). ` +
        "New entries need a reason, an owner and an expiry written by hand.",
    );
    process.exit(0);
  }

  const baseline = JSON.parse(readFileSync(BASELINE, "utf8"));
  const failures = invalidationKeyFailures({
    literals,
    foreign,
    phantoms,
    baseline,
  });

  if (failures.length > 0) {
    for (const failure of failures)
      console.error(`\ninvalidation-keys: ${failure}`);
    process.exit(1);
  }

  if (!process.argv.includes("--quiet")) {
    console.log(
      `invalidation-keys: no literal keys; ${foreign.length} key(s) outside ` +
        `${REGISTRY} in ${baseline.exceptions.length} baselined file(s).`,
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
