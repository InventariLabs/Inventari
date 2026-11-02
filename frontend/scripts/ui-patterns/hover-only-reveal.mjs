import { classNameOf, lineAt, withoutComments } from "./lib.mjs";

/**
 * `opacity-0` paired with a hover reveal, in any of its spellings —
 * `group-hover:`, a named group (`group-hover/name:`), or a bare `hover:`.
 */
const HIDDEN = /(?:^|[\s"'`])(?:[a-z]+:)*opacity-0(?:$|[\s"'`])/;
const HOVER_REVEAL =
  /(?:^|[\s"'`])(?:[a-z]+:)*(?:group-)?hover(?:\/[a-z-]+)?:opacity-(?!0\b)/;

/**
 * The two things that make the pattern safe, either of which is enough:
 *
 * - a focus reveal, so a keyboard reaches what a mouse uncovers;
 * - and a breakpoint on the hiding itself (`md:opacity-0`), so below it —
 *   which is to say on a touch screen, where hover never happens — the
 *   control is simply visible.
 *
 * Both are wanted, and the rule asks for both: a focus reveal alone still
 * leaves a finger with nothing to tap, and a breakpoint alone still hides the
 * control from the keyboard on a laptop.
 */
const FOCUS_REVEAL =
  /(?:^|[\s"'`])(?:[a-z]+:)*(?:group-)?focus(?:-within)?(?:\/[a-z-]+)?:opacity-(?!0\b)/;
const RESPONSIVE_HIDE = /(?:^|[\s"'`])[a-z]+:opacity-0(?:$|[\s"'`])/;

/** A tooltip is not a control: nothing focuses it and nothing taps it. */
const NOT_A_CONTROL = /pointer-events-none/;

export default {
  name: "hover-only-reveal",
  says:
    "A control revealed by `opacity-0` + a hover class is invisible to a " +
    "keyboard and, below the hover breakpoint, to a finger — the first " +
    "signal that it exists arrives after the tap (UI_GUIDELINES §2.13c). " +
    "Three rows hid a destructive action this way: remove a member, delete " +
    "a notification, delete a file from object storage.",
  advice:
    "Pair the hiding with both guards, the way `RecipeCard` already does:\n" +
    "`md:opacity-0 md:group-hover:opacity-100 md:group-focus-within:opacity-100`\n" +
    "— visible below the breakpoint, and back on focus above it.",

  run(files) {
    const considered = files.filter((f) => /opacity-0/.test(f.text));
    const findings = [];

    for (const file of considered) {
      const text = withoutComments(file.text);
      // Read tag by tag: the two halves of the pattern have to sit on the
      // same element, and a `className` further down the file saying
      // `group-focus-within` does not protect this one.
      for (const m of text.matchAll(/<[A-Za-z][A-Za-z0-9.]*\b/g)) {
        const end = tagEndAt(text, m.index);
        if (end === -1) continue;
        const tag = text.slice(m.index, end + 1);
        const className = classNameOf(tag);
        if (!className) continue;
        if (!HIDDEN.test(className) || !HOVER_REVEAL.test(className)) continue;
        if (NOT_A_CONTROL.test(className)) continue;
        if (FOCUS_REVEAL.test(className) && RESPONSIVE_HIDE.test(className))
          continue;
        findings.push(`${file.path}:${lineAt(text, m.index)}`);
      }
    }

    return { considered: considered.length, findings };
  },
};

/**
 * The `>` closing the opening tag at `start`, quote- and brace-aware.
 *
 * `lib.mjs` exports the same walk only through `openingTags`, which needs a
 * component name; this rule does not know one — the pattern lands on a `div`
 * as readily as on a `Button`.
 */
function tagEndAt(text, start) {
  let depth = 0;
  let quote = null;

  for (let i = start; i < text.length; i++) {
    const ch = text[i];

    if (quote) {
      if (ch === "\\") i++;
      else if (ch === quote) quote = null;
      continue;
    }
    if (ch === '"' || ch === "'" || ch === "`") quote = ch;
    else if (ch === "{") depth++;
    else if (ch === "}") depth--;
    else if (ch === ">" && depth === 0) return i;
  }
  return -1;
}
