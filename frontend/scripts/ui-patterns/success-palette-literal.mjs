import { lineAt, withoutComments } from "./lib.mjs";

/**
 * A raw `emerald-*` / `green-*` class where the `success-*` token exists.
 *
 * UI_GUIDELINES §1.1 reserves the success scale for everything that means
 * "all good": the token is theme-aware and a profile can repaint it, while a
 * literal `bg-emerald-500` is whatever hue Tailwind shipped, in light and
 * dark mode alike. `accent-*` is not the answer either — ADR-013 lets a
 * profile repaint it with the brand colour, so it cannot carry the success
 * signal.
 *
 * The class was drained in the change that wrote this rule: one
 * emerald status dot plus three green ones a manual review had missed. The
 * `red-*` family is deliberately NOT claimed here — `destructive` has no
 * 50–900 scale, so a red finding is a design decision, not a swap, and is
 * left to the screens that own it. A rule that reports what it cannot
 * fix teaches everyone to skim its output.
 *
 * A colour that is identity rather than status — a swatch the user picked
 * for their widget — takes the escape hatch, with the reason at the call
 * site in the shape `destructive-outside-confirm` established:
 *
 *   {\/* ui-pattern: palette-identity — the swatch shows the colour the user
 *       chose as their widget's identity, not a status *\/}
 */
const PALETTE_LITERAL =
  /\b(?:bg|text|border|ring|divide|from|via|to|fill|stroke|decoration|caret|shadow|outline)-(?:emerald|green)-(?:50|[1-9]00)\b/g;

const EXCEPTION = /ui-pattern:\s*palette-identity\s*[—-]?\s*([^*}]+)/;
const MIN_REASON_WORDS = 5;
const LOOKBEHIND = 500;

export default {
  name: "success-palette-literal",
  corpus: "scripts",
  says:
    "A raw emerald-*/green-* class pins one hue where success semantics are " +
    "meant — the success-* token is theme-aware and profile-repaintable, " +
    "the literal is neither (UI_GUIDELINES §1.1).",
  advice:
    "Swap the literal for the success-* scale (bg-success-500,\n" +
    "text-success-600, border-success-300, …) — same hue today, themed\n" +
    "tomorrow. If the colour is identity rather than status (a swatch the\n" +
    "user picked), say so at the call site:\n" +
    "ui-pattern: palette-identity — <why the token would be wrong here>.",

  run(files) {
    const findings = [];

    for (const file of files) {
      // Match in the comment-free text so a doc comment quoting the class
      // as an example is not read as the mistake; offsets survive blanking,
      // so the exception lookup below still reads the raw text.
      const text = withoutComments(file.text);

      PALETTE_LITERAL.lastIndex = 0;
      let m;
      while ((m = PALETTE_LITERAL.exec(text)) !== null) {
        const before = file.text.slice(
          Math.max(0, m.index - LOOKBEHIND),
          m.index,
        );
        const reason = before.match(EXCEPTION)?.[1] ?? "";
        if (
          reason.trim().split(/\s+/).filter(Boolean).length >= MIN_REASON_WORDS
        )
          continue;

        findings.push(`${file.path}:${lineAt(text, m.index)}`);
      }
    }

    return { considered: files.length, findings };
  },
};
