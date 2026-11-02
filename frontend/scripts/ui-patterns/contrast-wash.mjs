import { lineAt, withoutComments } from "./lib.mjs";

/**
 * Text sitting on a translucent wash of its own colour.
 *
 * `bg-amber-500/10` over a white card is a barely-tinted surface; the
 * `text-amber-500` on top of it is the colour on a 10% wash of itself —
 * 1.99:1 where a 12px label needs 4.5:1 (on /inventory/stats).
 * The same shape kept recurring: `text-primary-500` on `bg-primary-500/10`
 * (3.29:1), deltas in `text-amber-600` (3.19:1), a counter badge measured
 * 1.04:1. The fix is never a darker guess per screen — it is the tint pair
 * the theme already carries: `bg-<status>-50` (or the dark-only
 * `dark:bg-<status>-500/10` rescue) with `text-on-<status>`, and for the
 * primary hue `text-primary-700 dark:text-primary-500`.
 *
 * The rule reads one string literal at a time: the wash and the text it
 * colours live in the same className (or in the string a helper returns for
 * one element — severity maps, chip factories). Cross-element pairs where a
 * tinted parent holds a neutral-text child are not a finding. `dark:`-prefixed
 * classes are skipped on both halves: `dark:bg-red-500/10 dark:text-red-300`
 * is the blessed dark rescue, and a dark-mode-only wash cannot break the
 * light theme it never renders in.
 *
 * A colour that is identity rather than status takes the escape hatch, with
 * the reason at the call site in the shape the other colour rules use:
 *
 *   {\/* ui-pattern: contrast-wash — the swatch shows the colour the user
 *       picked, not a status; it carries no text *\/}
 */
const HUES =
  "red|amber|yellow|orange|lime|green|emerald|teal|cyan|sky|blue|indigo|violet|purple|fuchsia|pink|rose|primary|accent|success";

// The wash: any translucent background of the hue. `bg-red-500/10`,
// `hover:bg-primary-500/15`, `bg-primary-50/50` — alpha is what makes it
// a wash over whatever surface is underneath.
const WASH = new RegExp(
  `(?<![\\w-])(?<!dark:)(?<!hover:)bg-(?:${HUES})-\\d{2,3}\\/\\d+`,
  "g",
);

// The text half: shade 300–600 fails on its own wash in the light theme
// (400/500 outright, 600 for anything under ~19px bold). 700+ is the
// blessed text step and stays out of the findings.
const TEXT = new RegExp(
  `(?<![\\w-])(?<!dark:)(?<!hover:)text-(?:${HUES})-(\\d{2,3})(?:\\/\\d+)?`,
  "g",
);

const hueOf = (s) => s.replace(/^(?:bg|text)-/, "").replace(/-\d{2,3}.*$/, "");
const EXCEPTION = /ui-pattern:\s*contrast-wash\s*[—-]?\s*([^*}]+)/;
const MIN_REASON_WORDS = 5;
const LOOKBEHIND = 500;

export default {
  name: "contrast-wash",
  corpus: "scripts",
  says:
    "Text of a colour sits on a translucent wash of the same colour — the " +
    "pair measures 2–3.5:1 in the light theme, below AA for anything under " +
    "19px bold (UI_GUIDELINES §1.1).",
  advice:
    "Pair the status tint with its text half instead: bg-<status>-50 (plus\n" +
    "dark:bg-<status>-500/10 for dark mode) with text-on-<status> — or, on\n" +
    "the primary hue, text-primary-700 dark:text-primary-500. If the colour\n" +
    "is identity rather than status (a swatch, a chart glyph), say so at the\n" +
    "call site:\n" +
    "ui-pattern: contrast-wash — <why the token pair would be wrong here>.",

  run(files) {
    const findings = [];

    for (const file of files) {
      const text = withoutComments(file.text);

      // Every string literal — classNames inline, but also the strings a
      // helper returns (getSeverityColor and its kin), which render as one
      // element's className all the same.
      const literal = /'([^'\\\n]+)'|"([^"\\\n]+)"|`([^`\\]+)`/g;
      let lit;
      while ((lit = literal.exec(text)) !== null) {
        const s = lit[1] ?? lit[2] ?? lit[3] ?? "";
        if (!s.includes("bg-")) continue;

        const washHues = new Set();
        WASH.lastIndex = 0;
        let m;
        while ((m = WASH.exec(s)) !== null) washHues.add(hueOf(m[0]));
        if (washHues.size === 0) continue;

        TEXT.lastIndex = 0;
        while ((m = TEXT.exec(s)) !== null) {
          const shade = parseInt(m[1], 10);
          if (shade < 300 || shade > 600) continue;
          if (!washHues.has(hueOf(m[0]))) continue;

          // The raw text, not the comment-stripped copy: withoutComments
          // blanks, so the offsets line up and an exception written in a
          // comment stays readable where it was written.
          const before = file.text.slice(
            Math.max(0, lit.index - LOOKBEHIND),
            lit.index,
          );
          const reason = before.match(EXCEPTION)?.[1] ?? "";
          if (
            reason.trim().split(/\s+/).filter(Boolean).length >=
            MIN_REASON_WORDS
          )
            continue;

          findings.push(`${file.path}:${lineAt(text, lit.index)}`);
          break;
        }
      }
    }

    return { considered: files.length, findings };
  },
};
