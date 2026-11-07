#!/usr/bin/env node
/**
 * check-empty-state.mjs
 *
 * A page's empty state is the first screen a new organization sees of a
 * module, and UI_GUIDELINES §11.7 asks it to read as an invitation: a title,
 * a description, and an action. The `<EmptyState>` component takes
 * `description` as an optional prop, so nothing stopped a page from shipping
 * the description inside the title — "No locations yet. Add your first."
 * rendered as one heading, in heading weight, over a button repeating the
 * second half.
 *
 * The rule is about pages, not about panels: a compact empty state inside a
 * card, a tab or a modal may stand as a single line. So this gate scans the
 * page files — `modules/<module>/pages/**\/*Page.tsx`, and the
 * `*EmptyState.tsx` helpers a page hands its empty state to — and flags every
 * `<EmptyState>` whose opening tag carries no `description` attribute.
 *
 * The AST, not a regex: a description can be a multi-line conditional
 * expression, and a tag can carry a spread no scan can read. A spread does
 * not count as a description — the sentence has to be visible to the reader
 * of the code and to this gate.
 *
 * Modes:
 *   node check-empty-state.mjs            # report, exit 1 on findings
 *   node check-empty-state.mjs --quiet    # exit code only
 */
import { readFileSync, readdirSync } from "node:fs";
import { resolve, relative, join } from "node:path";
import { pathToFileURL } from "node:url";
import ts from "typescript";

const ROOT = resolve(new URL("..", import.meta.url).pathname); // frontend/
const QUIET = process.argv.includes("--quiet");

/** A module's page file, relative to `src/`. Panels and tabs are not pages. */
const PAGE = /^modules\/[^/]+\/pages\/.*Page\.tsx$/;

/**
 * A page's empty state pulled out into its own component (function-length
 * extractions do this) keeps the page's duty, so a module file named
 * `*EmptyState.tsx` is scanned wherever it sits.
 */
const EMPTY_STATE_HELPER = /^modules\/[^/]+\/(?:.*\/)?[A-Za-z]*EmptyState\.tsx$/;

export function isScanned(rel) {
  return (
    (PAGE.test(rel) || EMPTY_STATE_HELPER.test(rel)) &&
    !/\.test\.tsx$/.test(rel)
  );
}

export function findViolations(files) {
  const findings = [];
  for (const file of files) {
    if (!isScanned(file.path)) continue;
    const source = ts.createSourceFile(
      file.path,
      file.text,
      ts.ScriptTarget.Latest,
      /* setParentNodes */ false,
      ts.ScriptKind.TSX,
    );
    const lineOf = (node) =>
      source.getLineAndCharacterOfPosition(node.getStart(source)).line + 1;
    const visit = (node) => {
      const tag = ts.isJsxOpeningElement(node)
        ? node.tagName
        : ts.isJsxSelfClosingElement(node)
          ? node.tagName
          : null;
      if (tag && tag.getText(source) === "EmptyState") {
        const hasDescription = node.attributes.properties.some(
          (property) =>
            ts.isJsxAttribute(property) &&
            property.name.getText(source) === "description",
        );
        if (!hasDescription) {
          findings.push(
            `${file.path}:${lineOf(node)}: <EmptyState> without description`,
          );
        }
      }
      ts.forEachChild(node, visit);
    };
    visit(source);
  }
  return findings.sort();
}

function walk(dir, out = []) {
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const full = join(dir, entry.name);
    if (entry.isDirectory()) walk(full, out);
    else if (entry.name.endsWith(".tsx")) out.push(full);
  }
  return out;
}

function runCli() {
  const SRC = resolve(ROOT, "src");
  const findings = findViolations(
    walk(SRC).map((file) => ({
      path: relative(SRC, file),
      text: readFileSync(file, "utf8"),
    })),
  );

  if (findings.length > 0) {
    if (!QUIET) {
      console.error(
        `empty-state: ${findings.length} page empty state(s) without a description:`,
      );
      for (const f of findings) console.error(`  ${f}`);
      console.error(
        "Give the page's empty state a description — title, description and action are the shape UI_GUIDELINES §11.7 asks of it (panels and cards keep theirs optional).",
      );
    }
    process.exit(1);
  }

  if (!QUIET) {
    console.log(
      "empty-state: every page empty state carries a description (0 findings).",
    );
  }
}

if (import.meta.url === pathToFileURL(process.argv[1] ?? "").href) {
  runCli();
}
