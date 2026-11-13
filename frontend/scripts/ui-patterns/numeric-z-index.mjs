import { lineAt, withoutComments } from "./lib.mjs";

/** An arbitrary-value class: `z-[100]`. */
const NUMERIC_CLASS = /\bz-\[-?\d+\]/g;
/** The value of a style object's `zIndex:`, up to the end of the property. */
const STYLE_VALUE = /\bzIndex:([^,}\n]*)/g;
const STRING_LITERAL = /"[^"]*"|'[^']*'|`[^`]*`/g;

export default {
  name: "numeric-z-index",
  corpus: "scripts",
  says:
    "A hand-written z-index number invents a layer the stacking table does " +
    "not have — the next overlay picks its own number and the two fight " +
    "(UI_GUIDELINES §4.1).",
  advice:
    "Use the layer token: `z-[var(--z-modal)]`, or `zIndex: \"var(--z-sticky)\"`\n" +
    "in a style object (the `--z-*` block of index.css). `<Sheet zIndex=\"…\">`\n" +
    "already takes the layer name. If no layer fits, the table gets a row first.",

  run(files) {
    const findings = [];

    for (const file of files) {
      const text = withoutComments(file.text);
      for (const match of text.matchAll(NUMERIC_CLASS)) {
        findings.push(`${file.path}:${lineAt(text, match.index)}`);
      }
      for (const match of text.matchAll(STYLE_VALUE)) {
        // A number on either side of a ternary counts; the digits inside a
        // string (a token name) do not.
        if (/\d/.test(match[1].replace(STRING_LITERAL, ""))) {
          findings.push(`${file.path}:${lineAt(text, match.index)}`);
        }
      }
    }

    return { considered: files.length, findings };
  },
};
