#!/usr/bin/env node
/**
 * check-mutate-async-handled.mjs
 *
 * A refusal awaited by nobody is a refusal nobody reads.
 *
 * `useAppMutation` reports a failed `mutate(vars)` with a toast, and steps
 * aside for `mutateAsync(vars)`: the error is handed to whoever awaited it
 * (`frontend/src/lib/api/mutationFactory.ts`). A `mutateAsync` that nothing
 * catches therefore says nothing at all — the screen stays as it was, the
 * reader walks away believing the change was saved, and the console gets an
 * unhandled rejection.
 *
 * The scanner parses the file. A `mutateAsync` — called, or handed on as a
 * value (`const save = m.mutateAsync`, `{ mutateAsync: save } = useX()`) — is
 * handled when the promise reaches one of:
 *
 *   try { await m.mutateAsync(v) } catch (e) { … }    // a catch of its own
 *   m.mutateAsync(v).catch(…)  /  .then(ok, failed)    // a rejection handler
 *                        // (an empty catch or `() => {}` swallows the refusal
 *                        // and is a finding; `.catch()` with no handler hands
 *                        // it on and is followed further)
 *   runWithToast(() => m.mutateAsync(v), …)            // the toast helper
 *   <ConfirmDialog onConfirm={() => m.mutateAsync(v)}> // a component that
 *                                                      // catches (CATCHERS)
 *   { mutateAsync: async () => { await m.mutateAsync(v) } }
 *                                // a wrapper named mutateAsync: its callers
 *                                // are sites of their own and checked there
 *
 * A function the call sits in is followed through this file: a named handler
 * is handled when every place the file uses it is — called inside a try,
 * handed to a catching prop, wrapped in `useCallback`. A handler a hook
 * returns to another file cannot be followed, and is a finding.
 *
 * Modes:
 *   node check-mutate-async-handled.mjs                    # report and exit 1
 *   node check-mutate-async-handled.mjs --baseline         # only NEW findings fail
 *   node check-mutate-async-handled.mjs --write-baseline   # snapshot current
 *   node check-mutate-async-handled.mjs --quiet            # exit code only
 *
 * Baseline: frontend/scripts/mutate-async-baseline.json (count per site: file,
 * enclosing declaration, receiver). The goal is an empty baseline.
 */
import { readFileSync, readdirSync, writeFileSync, existsSync } from "node:fs";
import { resolve, relative } from "node:path";
import { fileURLToPath } from "node:url";
import ts from "typescript";

const ROOT = resolve(new URL("..", import.meta.url).pathname); // frontend/
const SRC = resolve(ROOT, "src");
const BASELINE_PATH = resolve(ROOT, "scripts/mutate-async-baseline.json");

/**
 * Props whose component awaits the promise it is handed and shows the
 * refusal itself. Each entry was read: the component catches the rejection
 * and puts the reason in front of the reader (ConfirmDialog keeps itself open
 * with it; the wrappers below hand their `onConfirm` to a ConfirmDialog).
 */
export const CATCHERS = {
  ConfirmDialog: ["onConfirm"],
  DeleteReasonDialog: ["onConfirm"],
  ConsumeDialog: ["onConfirm"],
  LotStatusDialog: ["onConfirm"],
  WorkflowSwitchOffDialog: ["onConfirm"],
  ItemsPageDialogs: ["onDelete", "onConsume"],
  ImportWizardSheet: ["run"],
  WebhookForm: ["onSave"],
  // Handed on to the approvals module's buttons, which catch and toast.
  POApprovalStatusCard: ["onApprove", "onRequest", "onReject"],
};

/**
 * Object-literal properties read the same way, by the call the object is
 * handed to (`showConfirm({ onConfirm })` opens a ConfirmDialog, and
 * `useConfirmDialog` hands the action's promise back to it) or by the
 * slot whose `data` it is (the approvals module's buttons catch).
 */
const CATCHING_CALL_PROPERTIES = { showConfirm: ["onConfirm"] };
const CATCHING_SLOT_PROPERTIES = {
  approval_status_badge: ["onApprove", "onRequest", "onReject"],
  approval_decision_panel: ["onApprove", "onReject"],
};

/** Calls that catch the promise of the function they are handed. */
const CATCHING_CALLS = new Set([
  "runWithToast",
  // The page's Save collects every part's refusal and toasts each one.
  "usePageSavePart",
]);

/** Calls that run their function argument and hand its promise back. */
const TRANSPARENT_CALLS = new Set(["useCallback", "map", "all", "then"]);

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

const calleeName = (call) => {
  const callee = call.expression;
  if (ts.isIdentifier(callee)) return callee.text;
  if (ts.isPropertyAccessExpression(callee)) return callee.name.text;
  return "";
};

const tagName = (attribute) => {
  const element = attribute.parent.parent; // JsxAttributes → opening element
  return element.tagName.getText();
};

/** The props an object literal's consumer catches for, by who it is handed to. */
function catchingPropertiesOf(object) {
  const holder = object.parent;
  if (ts.isCallExpression(holder) && holder.arguments.includes(object)) {
    return CATCHING_CALL_PROPERTIES[calleeName(holder)] ?? [];
  }
  const attribute = holder.parent;
  if (
    ts.isJsxExpression(holder) &&
    ts.isJsxAttribute(attribute) &&
    attribute.name.getText() === "data" &&
    tagName(attribute) === "TypedSlot"
  ) {
    const slot = attribute.parent.properties.find(
      (p) => ts.isJsxAttribute(p) && p.name.getText() === "name",
    );
    const name =
      slot?.initializer && ts.isStringLiteral(slot.initializer)
        ? slot.initializer.text
        : "";
    return CATCHING_SLOT_PROPERTIES[name] ?? [];
  }
  return [];
}

const propertyName = (node) =>
  node.name && (ts.isIdentifier(node.name) || ts.isStringLiteral(node.name))
    ? node.name.text
    : "";

/** Every identifier in the file spelled `name`, except its declaration. */
function usesOf(source, name, declaration) {
  const uses = [];
  const visit = (node) => {
    if (
      ts.isIdentifier(node) &&
      node.text === name &&
      node !== declaration &&
      !(ts.isPropertyAccessExpression(node.parent) && node.parent.name === node)
    ) {
      uses.push(node);
    }
    ts.forEachChild(node, visit);
  };
  visit(source);
  return uses;
}

/**
 * Whether a value standing at `node` — a promise, or a function returning
 * one — ends where a refusal is shown. `seen` breaks recursion between
 * handlers that call each other.
 */
function reachesHandler(source, node, seen) {
  // A try's catch sees a rejection only through an `await` between it and
  // the promise; a statement that neither awaits nor returns the promise
  // drops it, whatever catches above.
  let awaited = false;
  for (let cur = node; cur.parent; cur = cur.parent) {
    const parent = cur.parent;
    // Past a function's edge the value is the function, or what it returns.
    if (ts.isFunctionLike(cur) && cur !== node) awaited = false;
    if (ts.isAwaitExpression(parent)) awaited = true;
    if (
      (ts.isExpressionStatement(parent) && !awaited) ||
      ts.isVoidExpression(parent)
    ) {
      return false;
    }
    if (ts.isTryStatement(parent) && parent.tryBlock === cur) {
      // An empty catch swallows the refusal: nobody is told.
      if (parent.catchClause && awaited) {
        return parent.catchClause.block.statements.length > 0;
      }
    }
    if (ts.isPropertyAccessExpression(parent) && parent.expression === cur) {
      const call = parent.parent;
      const arm =
        ts.isCallExpression(call) && call.expression === parent
          ? { catch: call.arguments[0], then: call.arguments[1] }[
              parent.name.text
            ]
          : undefined;
      // No rejection arm hands the rejection on to the chained promise; an
      // arm that does nothing swallows it.
      if (arm && !isAbsent(arm)) return !isEmptyFunction(arm);
    }
    if (ts.isJsxExpression(parent) && ts.isJsxAttribute(parent.parent)) {
      const props = CATCHERS[tagName(parent.parent)] ?? [];
      return props.includes(parent.parent.name.getText());
    }
    if (
      (ts.isPropertyAssignment(parent) && parent.initializer === cur) ||
      ts.isShorthandPropertyAssignment(parent)
    ) {
      const name = propertyName(parent);
      if (name === "mutateAsync") return true;
      if (catchingPropertiesOf(parent.parent).includes(name)) return true;
    }
    if (ts.isCallExpression(parent) && parent.arguments.includes(cur)) {
      const callee = calleeName(parent);
      if (CATCHING_CALLS.has(callee)) return true;
      if (!TRANSPARENT_CALLS.has(callee)) return false;
      continue;
    }
    // A named function, promise or `mutateAsync` is followed to every place
    // this file uses it — not an awaited result, which is plain data.
    const named =
      (ts.isVariableDeclaration(parent) &&
        parent.initializer === cur &&
        (cur === node || ts.isFunctionLike(cur) || isTransparent(cur)) &&
        ts.isIdentifier(parent.name) &&
        parent.name) ||
      (ts.isFunctionDeclaration(cur) && cur.name) ||
      null;
    if (named) return usesHandled(source, named, seen);
    if (ts.isFunctionLike(cur) && cur !== node) {
      // A function nobody named and nothing above catches for: an inline
      // `onClick={async () => …}`, a `setTimeout` callback.
      return false;
    }
  }
  return false;
}

/** `undefined` or `null` in a callback's place: no callback at all. */
const isAbsent = (node) =>
  (ts.isIdentifier(node) && node.text === "undefined") ||
  node.kind === ts.SyntaxKind.NullKeyword;

/** `() => {}`, `function () {}`, `() => undefined`: a callback that does nothing. */
const isEmptyFunction = (node) =>
  (ts.isArrowFunction(node) || ts.isFunctionExpression(node)) &&
  (ts.isBlock(node.body)
    ? node.body.statements.length === 0
    : isAbsent(node.body));

const isTransparent = (node) =>
  ts.isCallExpression(node) && TRANSPARENT_CALLS.has(calleeName(node));

function usesHandled(source, declaration, seen) {
  if (seen.has(declaration)) return true;
  seen.add(declaration);
  const uses = usesOf(source, declaration.text, declaration).filter(
    // A dependency list mentions the handler without running it.
    (use) => !ts.isArrayLiteralExpression(use.parent),
  );
  if (uses.length === 0) return false;
  return uses.every((use) => reachesHandler(source, use, seen));
}

/** Name of the nearest named declaration holding `node`, for the baseline key. */
function ownerOf(node) {
  for (let cur = node.parent; cur; cur = cur.parent) {
    if (
      ts.isVariableDeclaration(cur) &&
      ts.isIdentifier(cur.name) &&
      cur.initializer &&
      (ts.isFunctionLike(cur.initializer) ||
        // `useCallback(async () => …)`, not `m.mutateAsync(v)` itself.
        (ts.isCallExpression(cur.initializer) &&
          cur.initializer.arguments.some(ts.isFunctionLike)))
    ) {
      return cur.name.text;
    }
    if (
      (ts.isFunctionDeclaration(cur) || ts.isMethodDeclaration(cur)) &&
      cur.name
    ) {
      return cur.name.getText();
    }
    if (ts.isPropertyAssignment(cur) || ts.isJsxAttribute(cur)) {
      return cur.name.getText();
    }
  }
  return "<module>";
}

export function unhandledIn(rel, text) {
  const source = ts.createSourceFile(
    rel,
    text,
    ts.ScriptTarget.Latest,
    /* setParentNodes */ true,
    rel.endsWith(".tsx") ? ts.ScriptKind.TSX : ts.ScriptKind.TS,
  );
  const sites = [];
  const visit = (node) => {
    if (
      ts.isPropertyAccessExpression(node) &&
      node.name.text === "mutateAsync"
    ) {
      sites.push({
        node,
        receiver: `${node.expression.getText(source)}.mutateAsync`,
      });
    }
    // `const { mutateAsync: save } = useX()` — every use of `save` is a site.
    if (
      ts.isBindingElement(node) &&
      (node.propertyName ?? node.name).getText(source) === "mutateAsync" &&
      ts.isIdentifier(node.name)
    ) {
      for (const use of usesOf(source, node.name.text, node.name)) {
        if (ts.isArrayLiteralExpression(use.parent)) continue;
        sites.push({ node: use, receiver: node.name.text });
      }
    }
    ts.forEachChild(node, visit);
  };
  visit(source);

  const findings = [];
  for (const { node, receiver } of sites) {
    const call =
      ts.isCallExpression(node.parent) && node.parent.expression === node
        ? node.parent
        : node;
    if (reachesHandler(source, call, new Set())) continue;
    findings.push({
      file: rel,
      line:
        source.getLineAndCharacterOfPosition(node.getStart(source)).line + 1,
      site: `${ownerOf(node)} :: ${receiver}`,
    });
  }
  return findings;
}

export function tally(findings) {
  const counts = new Map();
  for (const f of findings) {
    const key = `${f.file} :: ${f.site}`;
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
  const findings = files.flatMap((rel) => {
    const text = readFileSync(resolve(SRC, rel), "utf8");
    return text.includes("mutateAsync") ? unhandledIn(rel, text) : [];
  });

  if (writeBaseline) {
    writeFileSync(
      BASELINE_PATH,
      JSON.stringify(
        { unhandled: Object.fromEntries([...tally(findings)].sort()) },
        null,
        2,
      ) + "\n",
    );
    console.log(
      `mutate-async baseline written: ${findings.length} site(s) → scripts/mutate-async-baseline.json`,
    );
    process.exit(0);
  }

  const baseline =
    useBaseline && existsSync(BASELINE_PATH)
      ? JSON.parse(readFileSync(BASELINE_PATH, "utf8")).unhandled
      : {};
  const { added, fixed } = diffBaseline(findings, baseline);

  if (added.length > 0) {
    console.error(
      `\nmutate-async: ${added.length} NEW mutateAsync site(s) nothing catches\n`,
    );
    for (const { key, was, now } of added) {
      console.error(was === 0 ? `  ${key}` : `  ${key}  (${was} → ${now})`);
    }
    for (const f of findings) {
      if (added.some(({ key }) => key === `${f.file} :: ${f.site}`)) {
        console.error(`    at src/${f.file}:${f.line}`);
      }
    }
    console.error(
      "\nA refused mutateAsync reaches the reader only through whoever " +
        "awaited it. Call `mutate` (the factory toasts the refusal), or " +
        "catch it and say something: try/catch, runWithToast, or a " +
        "component that shows the reason (ConfirmDialog's onConfirm).",
    );
    process.exit(1);
  }

  if (!quiet) {
    const total = [...tally(findings).values()].reduce((a, b) => a + b, 0);
    console.log(
      `mutate-async: ${files.length} file(s) scanned, ${total} site(s) (all in the baseline).`,
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
