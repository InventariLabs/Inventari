#!/usr/bin/env node
/**
 * check-dialog-names.mjs
 *
 * Every dialog says what it is.
 *
 * A `<Sheet>` renders `role="dialog"` with `aria-modal`. Without a name, a
 * screen reader announces "dialog" and nothing else — or, worse, reads the
 * whole panel as one run-on sentence. Four such dialogs were once found in a
 * row; a fifth had wired its heading id to `aria-describedby`, so it had a
 * description and no name at all.
 *
 * A dialog passes when its opening tag carries `aria-label` or
 * `aria-labelledby`. Radix dialogs (`<DialogContent>` with `<DialogTitle>`)
 * are named by Radix itself and are not scanned here.
 *
 * The second rule exists because the first one was blind: it reads
 * windows that *declared* a role and stopped short of a name, and says
 * nothing about a window that never declared one. The
 * post-cooking rating screen covered the whole viewport, held no focus and
 * ignored Escape — and this gate called the tree clean. So: an element in the
 * fullscreen layer is a screen standing in front of the app, and has to say
 * `role="dialog"`. Once it does, the naming rule above applies to it too.
 *
 * The third rule answers the same blindness one step further on. The storage
 * wizard declared the role — so it passed everything above — and answered no
 * key at all: Escape moved focus to the cross and the sheet stayed open. A
 * window that covers the application and calls itself a dialog owes the reader
 * an exit, so the declaration now has to come with one: the component renders
 * the surface through the primitive that brings the key (`<Sheet>`, Radix's
 * dialog), or answers Escape itself.
 *
 * That evidence is read from the component that renders the overlay — not
 * from the file at large — and has to be used. Three probes broke the first
 * version, which tested the whole file for the bare string "Escape": a
 * comment mentioning the key was enough, an import nobody called was enough,
 * and the layer had to be written as a class, so `style={{ zIndex: … }}` —
 * the idiom `Sheet` itself uses — was invisible. A fourth: the rule knew the
 * fullscreen layer and nothing else, while a hand-rolled `role="dialog"` on
 * `--z-modal` is a dialog in exactly the same way.
 *
 * Modes:
 *   node check-dialog-names.mjs             # report and exit 1 on findings
 *   node check-dialog-names.mjs --quiet     # exit code only
 */
import { readFileSync, readdirSync } from "node:fs";
import { resolve, relative } from "node:path";
import { fileURLToPath } from "node:url";

// `new URL(...).pathname`, not fileURLToPath: under vitest `import.meta.url`
// carries a `/@fs/` prefix that fileURLToPath refuses outright.
const ROOT = resolve(new URL("..", import.meta.url).pathname); // frontend/
const SRC = resolve(ROOT, "src");

function walk(dir, out = []) {
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const full = resolve(dir, entry.name);
    if (entry.isDirectory()) walk(full, out);
    else out.push(full);
  }
  return out;
}

export function isScanned(rel) {
  if (!rel.endsWith(".tsx")) return false;
  if (/\.test\.tsx$/.test(rel)) return false;
  // The component itself: it is what *reads* the props.
  if (rel === "components/ui/Sheet.tsx") return false;
  return true;
}

/**
 * The opening `<Sheet ...>` tags in a file, as text.
 *
 * Scans to the matching `>` while counting braces, because a prop value can
 * contain one (`onClose={() => setOpen(false)}`) and a regex that stops at
 * the first `>` would cut the tag in half.
 */
export function sheetTags(text) {
  const tags = [];
  const opener = /<Sheet(?=[\s/>])/g;
  let match;
  while ((match = opener.exec(text)) !== null) {
    let depth = 0;
    let i = match.index;
    for (; i < text.length; i++) {
      const char = text[i];
      if (char === "{") depth++;
      else if (char === "}") depth--;
      else if (char === ">" && depth === 0) break;
    }
    tags.push(text.slice(match.index, i + 1));
  }
  return tags;
}

/**
 * The modal z-layers (UI_GUIDELINES §4.1). A surface on any of them stands
 * over the application; longest name first, so the alternation built from
 * this list cannot read `--z-modal-nested` as `--z-modal`.
 */
export const MODAL_LAYERS = ["modal-nested", "fullscreen", "confirm", "modal"];

/**
 * The opening tags of elements parked on a modal z-layer, with their offsets.
 *
 * Two spellings count — `z-[var(--z-modal)]` inside a `className` and the
 * same layer written through `style={{ zIndex: "var(--z-modal)" }}`, which is
 * how `Sheet` itself sets it. Read like `sheetTags`, brace-aware, so a `>`
 * inside a prop does not end the tag early.
 */
function scanOverlayTags(text, layers = MODAL_LAYERS) {
  const pattern = [...layers].sort((a, b) => b.length - a.length).join("|");
  const marker = new RegExp(
    `className=[^]*z-\\[var\\(--z-(?:${pattern})\\)\\]` +
      `|style=[^]*zIndex\\s*:\\s*["'\`]var\\(--z-(?:${pattern})\\)["'\`]`,
  );
  const tags = [];
  // A tag name may carry dots — `<AlertDialogPrimitive.Overlay>` is the idiom
  // `ConfirmDialog` itself uses.
  const opener = /<[a-zA-Z][a-zA-Z0-9]*(?:\.[a-zA-Z][a-zA-Z0-9]*)*(?=[\s/>])/g;
  let match;
  while ((match = opener.exec(text)) !== null) {
    let depth = 0;
    let i = match.index;
    for (; i < text.length; i++) {
      const char = text[i];
      if (char === "{") depth++;
      else if (char === "}") depth--;
      else if (char === ">" && depth === 0) break;
    }
    const tag = text.slice(match.index, i + 1);
    // The layer has to sit on this very tag; a lookup table mapping tiers to
    // classes mentions the same string and is not an overlay.
    if (marker.test(tag) || numericLayer(tag, layers))
      tags.push({ index: match.index, tag });
  }
  return tags;
}

/**
 * The layer written as a number — `z-50`, `z-[400]`, `zIndex: 400`.
 *
 * The guidelines forbid it, and `UomSelect` does it anyway. A number at or
 * above the lowest modal token stands over the application whatever it is
 * called; a smaller one counts only when the element is `fixed inset-0`, i.e.
 * covers the viewport. A value of 400 or more is the fullscreen layer.
 */
const MODAL_FLOOR = 100;
const FULLSCREEN_FLOOR = 400;

function numericLayer(tag, layers) {
  const values = [
    ...[...tag.matchAll(/(?<![\w-])z-\[?(\d+)\]?(?![\w-])/g)].map((m) => +m[1]),
    ...[...tag.matchAll(/zIndex\s*:\s*(\d+)/g)].map((m) => +m[1]),
  ];
  const covers = /(?<![\w-])fixed(?![\w-])/.test(tag) && /inset-0/.test(tag);
  return values.some((value) => {
    if (value < MODAL_FLOOR && !covers) return false;
    const layer = value >= FULLSCREEN_FLOOR ? "fullscreen" : "modal";
    return layers.includes(layer);
  });
}

export function overlayLayerTags(text, layers = MODAL_LAYERS) {
  return scanOverlayTags(text, layers).map(({ tag }) => tag);
}

// `alertdialog` is a dialog: it covers the application and owes the same exit.
const DIALOG_ROLE = /role="(?:alert)?dialog"/;

export function undeclaredIn(rel, text) {
  return scanOverlayTags(text, ["fullscreen"])
    .filter(({ tag }) => !DIALOG_ROLE.test(tag))
    .map(() => rel);
}

/**
 * The unit the evidence is read from: the component that renders the overlay.
 *
 * A file holds several — a screen and the list it opens, a hook and the form
 * that calls it. Evidence counts inside the one the overlay stands in, which
 * is the nearest top-level definition at or above the tag, up to the next
 * one. Definitions are read at column zero, the way this tree formats them.
 */
const COMPONENT_START =
  /^(?:(?:export\s+)?(?:default\s+)?function\s+[A-Za-z0-9_]+|(?:export\s+)?(?:const|let|var)\s+[A-Za-z0-9_]+\s*=\s*(?:React\.)?(?:forwardRef|memo|function|\()|(?:export\s+)?class\s+[A-Za-z0-9_]+)/gm;

function componentAround(text, index) {
  const starts = [];
  COMPONENT_START.lastIndex = 0;
  let match;
  while ((match = COMPONENT_START.exec(text)) !== null)
    starts.push(match.index);

  let begin = 0;
  let end = text.length;
  for (const start of starts) {
    if (start <= index) begin = start;
    else {
      end = start;
      break;
    }
  }
  return text.slice(begin, end);
}

/**
 * Comments are not code. A rule that read them as evidence would accept a
 * sentence about the key on a screen that answers nothing — the first probe
 * that broke the rule was exactly that comment.
 */
function withoutComments(text) {
  return text.replace(/\/\*[^]*?\*\//g, "").replace(/\/\/[^\n]*/g, "");
}

/**
 * The evidence that a surface closes when Escape is pressed.
 *
 * Deliberately literal, because the cost of a wrong verdict is asymmetric:
 * a rule that guesses will one day report a dialog that is already right, and
 * the reader learns to skip the output. Two kinds of evidence count — the key
 * handled in this component, spelled the way this tree spells it
 * (`if (e.key === "Escape")`, `onEscapeKeyDown`), and the shared primitive
 * that brings the key with it (`<Sheet>`, a Radix dialog element). The
 * primitive has to be *rendered* here: an import nobody calls is a dead line,
 * not an exit, which is what the fourth probe showed.
 */
const ANSWERS_ESCAPE = [
  /\.key\s*(?:===|!==|==|!=)\s*["'`]Escape["'`]/,
  /["'`]Escape["'`]\s*(?:===|!==|==|!=)\s*[A-Za-z0-9_$.]*\.key/,
  /keyCode\s*(?:===|!==|==|!=)\s*27\b/,
  /onEscapeKeyDown/,
];
const RENDERS_SHEET = /<Sheet(?=[\s/>])/;
// Only the element that carries the key counts: `Content` listens for Escape,
// while `<AlertDialogFooter>` is a layout div that merely shares the prefix.
const RENDERS_RADIX_DIALOG =
  /<(?:[A-Za-z0-9_$]*Dialog[A-Za-z0-9_$]*\.Content|(?:Alert)?DialogContent)(?=[\s/>])/;

function answersEscapeIn(component) {
  const code = withoutComments(component);
  if (RENDERS_SHEET.test(code)) return true;
  if (RENDERS_RADIX_DIALOG.test(code)) return true;
  return ANSWERS_ESCAPE.some((pattern) => pattern.test(code));
}

/**
 * Dialogs on a modal layer that declare `role="dialog"` and show no way out.
 *
 * The role was the whole of the second rule, and that role alone misses
 * something: the storage wizard rendered its own `role="dialog"`, so it
 * passed this gate and answered nothing — the keyboard pressed at it moved
 * focus to the cross and stayed there. A window that covers the application
 * and declares itself a dialog owes the reader an exit, so the declaration
 * now has to come with one, in the component that renders it.
 *
 * An element on a modal layer with no role is not this rule's business —
 * `undeclaredIn` reports the fullscreen ones.
 */
export function undismissibleIn(rel, text) {
  return scanOverlayTags(text)
    .filter(({ tag }) => DIALOG_ROLE.test(tag))
    .filter(({ index }) => !answersEscapeIn(componentAround(text, index)))
    .map(() => rel);
}

export function unnamedIn(rel, text) {
  return sheetTags(text)
    .filter((tag) => !/aria-label(ledby)?[=\s]/.test(tag))
    .map(() => rel);
}

function main() {
  const files = walk(SRC)
    .map((f) => relative(SRC, f).split("\\").join("/"))
    .filter(isScanned);

  const sources = new Map(
    files.map((rel) => [rel, readFileSync(resolve(SRC, rel), "utf8")]),
  );

  const findings = files.flatMap((rel) => unnamedIn(rel, sources.get(rel)));
  const undeclared = files.flatMap((rel) =>
    undeclaredIn(rel, sources.get(rel)),
  );
  const undismissible = files.flatMap((rel) =>
    undismissibleIn(rel, sources.get(rel)),
  );

  if (
    findings.length > 0 ||
    undeclared.length > 0 ||
    undismissible.length > 0
  ) {
    if (findings.length > 0) {
      console.error(
        `dialog-names: ${findings.length} dialog(s) with no name\n`,
      );
      for (const f of new Set(findings)) console.error(`  ${f}`);
      console.error(
        "\nGive the <Sheet> an aria-labelledby pointing at its heading, or an " +
          "aria-label where it has none.",
      );
    }
    if (undeclared.length > 0) {
      console.error(
        `\ndialog-names: ${undeclared.length} fullscreen overlay(s) with no role\n`,
      );
      for (const f of new Set(undeclared)) console.error(`  ${f}`);
      console.error(
        "\nA surface on the fullscreen layer covers the application: give it " +
          'role="dialog", aria-modal, a name, a focus trap and Escape — or ' +
          "render it through <Sheet>, which brings all five.",
      );
    }
    if (undismissible.length > 0) {
      console.error(
        `\ndialog-names: ${undismissible.length} modal dialog(s) that answer no key\n`,
      );
      for (const f of new Set(undismissible)) console.error(`  ${f}`);
      console.error(
        "\nA window that declares itself a dialog and stands over the " +
          "application has to leave on Escape — asking first, if there is " +
          "something to lose. Render it through <Sheet>, which brings the " +
          "key, the focus trap and the name with it, or listen for it in the " +
          "component that renders it.",
      );
    }
    process.exit(1);
  }

  if (!process.argv.includes("--quiet")) {
    console.log(
      `dialog-names: all ${files.length} file(s) declare and name their dialogs.`,
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
