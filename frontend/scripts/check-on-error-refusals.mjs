#!/usr/bin/env node
/**
 * check-on-error-refusals.mjs
 *
 * A refusal handler that throws its argument away throws away the backend's
 * sentence.
 *
 * `onError: () => toast.error(constant)` cannot read the error it was
 * handed. The mutationFactory's default handler answers with
 * `extractApiError(error, fallback)`: the backend's own sentence in the
 * reader's language when there is one, the caller's constant when there is
 * not. A handler that opts out of that and prints a canned line prints a
 * lie whenever the server told the truth ("this shelf is full", "the period
 * is closed").
 *
 * The rule is about READING, not about punctuation, so the scanner parses
 * the file instead of grepping it. A violation is an `onError` property
 * whose handler never references the error it was handed:
 *
 *   onError: () => toast.error("Request failed")     // not handed, not read
 *   onError: (_err) => toast.error("Request failed") // handed, still unread
 *   onError: (err) => toast.error("Request failed")  // handed, still unread
 *   onError: function () { toast.error("…") }        // no parameter at all
 *   onError: handleRefusal                            // zero-parameter target
 *   onError() { toast.error("…") }                   // method shorthand
 *
 * Passing shapes: the body reads the error — `extractApiError(err, fallback)`,
 * `isNotFoundError(err)`, `console.error(err)` — or the property sits in a
 * type declaration (`onError: () => void`), which is a signature, not a
 * handler, and the AST does not show it as one.
 *
 * Modes:
 *   node check-on-error-refusals.mjs            # report, exit 1 on findings
 *   node check-on-error-refusals.mjs --quiet    # exit code only
 */
import { readFileSync, readdirSync } from "node:fs";
import { join, relative } from "node:path";
import { pathToFileURL } from "node:url";
import ts from "typescript";

const ROOT = resolve_src();
const QUIET = process.argv.includes("--quiet");

function resolve_src() {
  const here = new URL(".", import.meta.url).pathname;
  return join(here, "..", "src");
}

function walk(dir, out = []) {
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const full = join(dir, entry.name);
    if (entry.isDirectory()) walk(full, out);
    else out.push(full);
  }
  return out;
}

export function findViolations(files) {
  const findings = [];
  for (const file of files) {
    const kind = /\.tsx$/.test(file.path)
      ? ts.ScriptKind.TSX
      : ts.ScriptKind.TS;
    const source = ts.createSourceFile(
      file.path,
      file.text,
      ts.ScriptTarget.Latest,
      /* setParentNodes */ true,
      kind,
    );
    const lineOf = (node) =>
      source.getLineAndCharacterOfPosition(node.getStart(source)).line + 1;
    eachNode(source, (node) => {
      if (!propertyIsOnError(node)) return;
      const handler = ts.isPropertyAssignment(node) ? node.initializer : node; // method shorthand: onError() { … }
      const where = lineOf(node);

      if (ts.isIdentifier(handler)) {
        if (readsNothingInFile(source, handler.text, where)) {
          findings.push(
            `${file.path}:${where}: onError: ${handler.text}() — the handler takes no error`,
          );
        }
        return;
      }
      if (
        !ts.isArrowFunction(handler) &&
        !ts.isFunctionExpression(handler) &&
        !ts.isMethodDeclaration(handler)
      ) {
        return;
      }
      if (handler.body === undefined || handler.body === null) return; // type signature
      const params = handler.parameters.map((p) => p.name.getText(source));
      if (params.length === 0) {
        findings.push(
          `${file.path}:${where}: onError takes no error — it cannot read the refusal`,
        );
        return;
      }
      const bodyText = handler.body.getText(source);
      const reads = params.some((name) => mentionsWord(bodyText, name));
      if (!reads) {
        findings.push(
          `${file.path}:${where}: onError takes the refusal (${params.join(", ")}) but never reads it`,
        );
      }
    });
  }
  return findings.sort();
}

function eachNode(node, visit) {
  visit(node);
  ts.forEachChild(node, (child) => eachNode(child, visit));
}

function propertyIsOnError(node) {
  const name =
    ts.isPropertyAssignment(node) || ts.isMethodDeclaration(node)
      ? node.name
      : undefined;
  if (!name) return false;
  const text = name.getText();
  return text === "onError" || text === '"onError"' || text === "'onError'";
}

/** Is the named handler, declared in this same file, one that reads an error? */
function readsNothingInFile(source, name, where) {
  let target = null;
  eachNode(source, (node) => {
    if (target) return;
    if (ts.isFunctionDeclaration(node) && node.name?.getText() === name) {
      target = node;
    }
    if (
      ts.isVariableDeclaration(node) &&
      node.name.getText() === name &&
      (ts.isArrowFunction(node.initializer) ||
        ts.isFunctionExpression(node.initializer))
    ) {
      target = node.initializer;
    }
  });
  if (!target) return false; // declared elsewhere — not this file's business
  const params = target.parameters.map((p) => p.name.getText());
  if (params.length > 0) {
    const body = target.body?.getText() ?? "";
    if (params.some((param) => mentionsWord(body, param))) return false;
  }
  return true;
}

/** Word-boundary match: `toast.error(…)` must not count as a read of `err`. */
function mentionsWord(text, name) {
  return new RegExp(`\\b${name.replace(/[$]/g, "\\$")}\\b`).test(text);
}

function runCli() {
  const findings = findViolations(
    walk(ROOT)
      .filter((file) => /\.(ts|tsx)$/.test(file))
      .filter((file) => !/\.test\.(ts|tsx)$/.test(file))
      .map((file) => ({
        path: relative(ROOT, file),
        text: readFileSync(file, "utf8"),
      })),
  );

  if (findings.length > 0) {
    if (!QUIET) {
      console.error(
        `on-error-refusals: ${findings.length} handler(s) throw the refusal away:`,
      );
      for (const f of findings) console.error(`  ${f}`);
      console.error(
        "Read the refusal through extractApiError(err, fallback) instead — the error is the argument the handler was handed.",
      );
    }
    process.exit(1);
  }

  if (!QUIET) {
    console.log(
      "on-error-refusals: every onError handler reads (or names) the refusal it was handed (0 findings).",
    );
  }
}

if (import.meta.url === pathToFileURL(process.argv[1] ?? "").href) {
  runCli();
}
