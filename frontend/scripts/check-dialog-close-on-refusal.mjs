#!/usr/bin/env node
/**
 * check-dialog-close-on-refusal.mjs
 *
 * A dialog that closes before it knows whether the server accepted the
 * change takes the typed answer with it — and says why only in a toast that
 * is already fading. The reader has to open the dialog again, retype the
 * note, and guess whether the first attempt landed.
 *
 * The 2026-11 QA round met the class twice on screens that had been fixed
 * before on their error text: a run's Finish, Start, Put on hold, Undo and
 * Cancel closed their confirm dialog on the click and read the refusal in a
 * toast, and the recipes bulk Tag, an approval "Approve with a note" and a
 * rename tag did the same. The twins that are right — New Recipe, Copy plan,
 * Add to list — keep the dialog open and put the server's sentence in it.
 *
 * The rule reads the order of the two things in one handler. A surface is
 * closed by `onClose()`, `close()`, `dismiss()`, or a state setter whose name
 * ends in `Open`, `Dialog`, `Modal`, `Sheet`, `Confirm`, `Asking`, `Visible`,
 * `Shown`, `Picker` or `Panel` and is given `false`, `null` or `{ type:
 * "none" }`. A refusal is asked for by `.mutate(…)`, `.mutateAsync(…)` or a
 * prop callback named `onSave`, `onConfirm`, `onSubmit`, `onApprove`, `onTag`
 * and the like (never `onClose`, `onCancel`, `onDismiss`, `onOpen`).
 *
 * A close passes when it can only run on the acceptance: after an awaited
 * mutation in the same handler, inside the `onSuccess` of a mutation, or
 * inside `.then(…)`.
 *
 * A close is a finding when it runs before the mutation, after an un-awaited
 * one, in `onSettled` (which runs on the refusal too), in `finally`, in
 * `catch`, or in `onError` — the dialog is gone exactly when the reader
 * needs it.
 *
 * The scan is narrow where the class is. A file is read when it draws a
 * dialog-shaped component and holds a controlled text field, or when the
 * handler sits in a dialog's `onConfirm`/`onSubmit`/`onSave`; an action
 * sheet that closes after handing the work to the page above has nothing
 * typed to lose. The handler is followed into a local function it calls
 * (`onConfirm={() => { setOpen(false); save(); }}`), one hop.
 *
 * Modes:
 *   node check-dialog-close-on-refusal.mjs                    # report and exit 1
 *   node check-dialog-close-on-refusal.mjs --baseline         # only NEW findings fail
 *   node check-dialog-close-on-refusal.mjs --write-baseline   # snapshot current
 *   node check-dialog-close-on-refusal.mjs --quiet            # exit code only
 *
 * Baseline: frontend/scripts/dialog-close-baseline.json (one entry per file
 * and handler). The goal is an empty baseline.
 */
import { existsSync, readFileSync, readdirSync, writeFileSync } from "node:fs";
import { join, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import ts from "typescript";

const ROOT = resolve(new URL("..", import.meta.url).pathname); // frontend/
const SRC = resolve(ROOT, "src");
const BASELINE_PATH = resolve(ROOT, "scripts/dialog-close-baseline.json");

/** A state setter that closes a surface. */
const CLOSING_SETTER =
  /^set[A-Za-z0-9_$]*?(?:Open|Dialog|Modal|Sheet|Confirm|Asking|Visible|Shown|Picker|Panel|Overlay|Renaming|Deleting|Merging|Editing)$/;

/** Calls that close a surface the reader was typing into. */
const CLOSING_CALL = new Set([
  "onClose",
  "close",
  "dismiss",
  "handleClose",
  "onDismiss",
  "hide",
]);

/**
 * A prop callback that carries the mutation the dialog was open for. The verb
 * list is the write half of the app's handlers; `onClose`, `onCancel` and
 * `onOpen` are the dialog's own controls and name nothing the server does.
 */
const WRITE_CALLBACK =
  /^on(?:Save|Confirm|Submit|Approve|Reject|Tag|Add|Create|Update|Delete|Remove|Finish|Start|Undo|Put|Rename|Upload|Send|Publish|Duplicate|Complete|Retry|Export|Import|Archive|Restore|Move|Reverse|Adjust|Receive|Pick|Execute|Apply|Link|Assign|Verify|Invite|Grant|Revoke)\w*$/;

/**
 * A file that draws a dialog or a sheet.
 *
 * The class is about a surface that covers the work and takes it away; a
 * popover that closes after a pick is a different thing and is not read
 * here. The components are the app's own primitives plus Radix's dialog.
 */
const DIALOG = /<[A-Z]\w*(?:Dialog|Sheet|Modal)\b|role="dialog"/;

/** A controlled text field, the work a close takes with it. */
const TYPED_STATE = /useState(?:<[^>]*>)?\(\s*["'`]/;

/** The attributes that hand a dialog its answer. */
const CONFIRM_ATTRIBUTE = /^on(?:Confirm|Submit|Save)$/;

const MUTATION = new Set(["mutate", "mutateAsync"]);

function walk(dir, out = []) {
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const full = join(dir, entry.name);
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

/** `.mutate(…)`, `.mutateAsync(…)` or a write-shaped `on…(…)` call. */
export function isMutationCall(node) {
  if (!ts.isCallExpression(node)) return false;
  const name = calleeName(node);
  if (MUTATION.has(name)) return true;
  return WRITE_CALLBACK.test(name);
}

/** The close this call performs, as short text, or null. */
export function closeName(node) {
  if (!ts.isCallExpression(node)) return null;
  const callee = node.expression;
  if (ts.isIdentifier(callee)) {
    if (CLOSING_CALL.has(callee.text)) return `${callee.text}()`;
    if (CLOSING_SETTER.test(callee.text)) {
      const value = node.arguments[0];
      if (!value) return null;
      if (
        value.kind === ts.SyntaxKind.FalseKeyword ||
        value.kind === ts.SyntaxKind.NullKeyword
      ) {
        return `${callee.text}(${value.getText()})`;
      }
      if (ts.isObjectLiteralExpression(value)) {
        const none = value.properties.some(
          (property) =>
            ts.isPropertyAssignment(property) &&
            ts.isStringLiteral(property.initializer) &&
            property.initializer.text === "none",
        );
        if (none) return `${callee.text}({ type: "none" })`;
      }
    }
  }
  return null;
}

/** Is `node` inside a callback property/argument the named call owns? */
function insideCallNamed(node, names, stopAt) {
  for (let cur = node.parent; cur && cur !== stopAt; cur = cur.parent) {
    if (ts.isCallExpression(cur) && names.includes(calleeName(cur))) {
      return true;
    }
    if (
      ts.isPropertyAssignment(cur) &&
      (ts.isIdentifier(cur.name) || ts.isStringLiteral(cur.name)) &&
      names.includes(cur.name.text)
    ) {
      return true;
    }
  }
  return false;
}

const inside = (node, names, stopAt) => insideCallNamed(node, names, stopAt);

/** The nearest enclosing function of `node`, not counting `node` itself. */
function enclosingFunction(node) {
  for (let cur = node.parent; cur; cur = cur.parent) {
    if (ts.isFunctionLike(cur)) return cur;
  }
  return null;
}

function functionName(fn, source) {
  if (fn.name && ts.isIdentifier(fn.name)) return fn.name.text;
  const parent = fn.parent;
  if (
    parent &&
    ts.isVariableDeclaration(parent) &&
    ts.isIdentifier(parent.name)
  )
    return parent.name.text;
  if (parent && ts.isPropertyAssignment(parent))
    return parent.name.getText(source);
  return "<arrow>";
}

/** Calls in `fn`'s own body, not in a nested function. */
function inBody(fn, visit) {
  const body = fn.body;
  if (!body) return;
  const walkNode = (node) => {
    if (node !== body && ts.isFunctionLike(node)) return;
    visit(node);
    ts.forEachChild(node, walkNode);
  };
  walkNode(body);
}

/**
 * The functions this file declares by name, so a handler that hands the work
 * to one of them (`onConfirm={() => { setOpen(false); save(); }}`) is read
 * through it. One hop, like the write gate: the write lives in the module's
 * own helper, not one call further.
 */
function localFunctions(source) {
  const byName = new Map();
  const visit = (node) => {
    if (ts.isFunctionDeclaration(node) && node.name) {
      byName.set(node.name.text, node);
    }
    if (
      ts.isVariableDeclaration(node) &&
      ts.isIdentifier(node.name) &&
      node.initializer &&
      (ts.isArrowFunction(node.initializer) ||
        ts.isFunctionExpression(node.initializer))
    ) {
      byName.set(node.name.text, node.initializer);
    }
    ts.forEachChild(node, visit);
  };
  visit(source);
  return byName;
}

/** The mutation calls and close calls a handler makes, in source order. */
export function handlerEvents(fn, local = new Map(), seen = new Set()) {
  const mutations = [];
  const closes = [];
  inBody(fn, (node) => {
    if (isMutationCall(node)) {
      const awaited = ts.isAwaitExpression(node.parent);
      mutations.push({ node, awaited });
    }
    if (
      ts.isCallExpression(node) &&
      ts.isIdentifier(node.expression) &&
      local.has(node.expression.text) &&
      !seen.has(node.expression.text)
    ) {
      seen.add(node.expression.text);
      const nested = handlerEvents(
        local.get(node.expression.text),
        local,
        seen,
      );
      mutations.push(...nested.mutations);
    }
    const closer = closeName(node);
    if (closer) closes.push({ node, name: closer });
  });
  return { mutations, closes };
}

/**
 * Is `fn` itself one of a request's callbacks, and which one?
 *
 * "success" closes safely, "refusal" closes on the answer the dialog is meant
 * to stay open for, and null means the function is a handler of its own,
 * read from its body.
 */
function callbackKind(fn) {
  let cur = fn;
  while (cur.parent && ts.isParenthesizedExpression(cur.parent))
    cur = cur.parent;
  const holder = cur.parent;
  if (!holder) return null;
  if (ts.isPropertyAssignment(holder)) {
    const name =
      ts.isIdentifier(holder.name) || ts.isStringLiteral(holder.name)
        ? holder.name.text
        : "";
    if (name === "onSuccess") return "success";
    if (name === "onSettled" || name === "onError") return "refusal";
  }
  if (
    ts.isCallExpression(holder) &&
    ts.isPropertyAccessExpression(holder.expression) &&
    holder.arguments.includes(cur)
  ) {
    const method = holder.expression.name.text;
    if (method === "then") return "success";
    if (method === "catch" || method === "finally") return "refusal";
  }
  return null;
}

/** Why the close at `node` is not a refusal-safe one, or null. */
export function closeIsRefusalSafe(node, fn, local = new Map()) {
  // Closing from a success callback is the right shape.
  const own = callbackKind(fn);
  if (own === "success") return null;
  if (own === "refusal") return "closes in a refusal path";
  if (inside(node, ["onSuccess", "then"], fn)) return null;

  // Closing from any of these runs on the refusal too.
  if (inside(node, ["onSettled", "onError"], fn)) {
    return "closes in a refusal path";
  }
  for (let cur = node.parent; cur && cur !== fn; cur = cur.parent) {
    if (ts.isCatchClause(cur)) return "closes in catch";
    if (ts.isTryStatement(cur.parent) && cur.parent.finallyBlock === cur) {
      return "closes in finally";
    }
  }

  const { mutations } = handlerEvents(fn, local);
  if (mutations.length === 0) return null;

  const start = node.getStart();
  const before = mutations.filter((m) => m.node.getStart() < start);
  const afterAwaited = mutations.some(
    (m) => m.awaited && m.node.getStart() < start,
  );

  if (before.length === 0) return "closes before the request";
  if (afterAwaited) return null;
  return "closes right after an un-awaited request";
}

/**
 * Findings for one file's text: `{ line, handler, close, reason }`.
 */
export function closeOnRefusalIn(rel, text) {
  const kind = /\.tsx$/.test(rel) ? ts.ScriptKind.TSX : ts.ScriptKind.TS;
  const source = ts.createSourceFile(
    rel,
    text,
    ts.ScriptTarget.Latest,
    /* setParentNodes */ true,
    kind,
  );
  const out = [];
  if (!DIALOG.test(text)) return out;

  // The handlers a dialog hands its answer to. An inline one is the attribute
  // value itself; a named one is written there by name, and both can keep the
  // dialog open only by returning the request's promise.
  const typed = TYPED_STATE.test(text);
  const confirmNames = new Set();
  const confirmNodes = new Set();
  const collect = (node) => {
    if (
      ts.isJsxAttribute(node) &&
      CONFIRM_ATTRIBUTE.test(node.name.getText())
    ) {
      const value = node.initializer;
      if (value && ts.isJsxExpression(value) && value.expression) {
        const expression = value.expression;
        if (ts.isIdentifier(expression)) confirmNames.add(expression.text);
        else confirmNodes.add(expression);
      }
    }
    ts.forEachChild(node, collect);
  };
  collect(source);

  const local = localFunctions(source);
  const visit = (node) => {
    if (ts.isFunctionLike(node) && node.body) {
      const name = functionName(node, source);
      if (!typed && !confirmNodes.has(node) && !confirmNames.has(name)) {
        ts.forEachChild(node, visit);
        return;
      }
      const { closes } = handlerEvents(node, local);
      for (const close of closes) {
        const reason = closeIsRefusalSafe(close.node, node, local);
        if (reason) {
          out.push({
            file: rel,
            line:
              source.getLineAndCharacterOfPosition(close.node.getStart()).line +
              1,
            handler: functionName(node, source),
            close: close.name,
            reason,
          });
        }
      }
    }
    ts.forEachChild(node, visit);
  };
  visit(source);
  return out;
}

const keyOf = (finding) => `${finding.file} :: ${finding.handler}`;

function readBaseline() {
  return existsSync(BASELINE_PATH)
    ? JSON.parse(readFileSync(BASELINE_PATH, "utf8")).sites
    : {};
}

function runCli() {
  const quiet = process.argv.includes("--quiet");
  const baselineMode = process.argv.includes("--baseline");
  const writeBaseline = process.argv.includes("--write-baseline");

  const files = walk(SRC)
    .map((file) => relative(SRC, file).split("\\").join("/"))
    .filter(isScanned);
  const findings = files.flatMap((rel) =>
    closeOnRefusalIn(rel, readFileSync(resolve(SRC, rel), "utf8")),
  );

  if (writeBaseline) {
    const sites = {};
    for (const finding of findings) sites[keyOf(finding)] = 1;
    const body = {
      generatedBy:
        "node scripts/check-dialog-close-on-refusal.mjs --write-baseline",
      note:
        "Dialogs that close before the server accepted the change. One entry " +
        "per file, handler and close call; a plain run fails on any entry the " +
        "tree no longer holds as well as on a new one, and --write-baseline " +
        "is the only writer.",
      sites,
    };
    writeFileSync(BASELINE_PATH, `${JSON.stringify(body, null, 2)}\n`);
    console.log(
      `dialog-close-baseline.json written: ${Object.keys(sites).length} ` +
        `dialog handler(s).`,
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
        `\ndialog-close-refusal: ${visible.length} handler(s) close before ` +
          `the server accepted:\n`,
      );
      for (const finding of visible) {
        console.error(
          `  ${finding.file}:${finding.line} :: ${finding.handler} :: ` +
            `${finding.close} — ${finding.reason}`,
        );
      }
      console.error(
        "\nClose the dialog in onSuccess (or after `await mutateAsync(…)`), " +
          "and leave it open on the refusal so the typed answer and the " +
          "server's sentence stay where the reader is.",
      );
    }
    process.exit(1);
  }

  if (baselineMode && paid.length > 0) {
    if (!quiet) {
      console.error(
        `\ndialog-close-refusal: ${paid.length} baselined site(s) are fixed ` +
          "— drop them with --write-baseline so the ratchet only turns down:\n",
      );
      for (const key of paid) console.error(`  ${key}`);
    }
    process.exit(1);
  }

  if (!quiet) {
    const scope = baselineMode ? "held by the baseline" : "in the tree";
    console.log(
      `dialog-close-refusal: ${findings.length} finding(s) ${scope} ` +
        `(${files.length} file(s) scanned).`,
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
