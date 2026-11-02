import { classNameOf, lineAt, tagEnd, withoutComments } from "./lib.mjs";

/**
 * The escape hatch, and the price of using it.
 *
 * The rule reads shapes, not intent, so a site where the seven really is the
 * typography table's code treatment gets to say so and stay — the JSX comment
 * form above the element, or the line form below, each carrying a sentence:
 *
 *   // ui-pattern: heavy-weight — the SKU and barcode are codes and the
 *   // monospace bold is the code treatment the typography table keeps
 *
 * The reason has to be a sentence — the same price as `error-message-as-copy`,
 * because a marker nobody had to write a reason for is a mute suppression.
 */
const MARKER =
  /ui-pattern:\s*heavy-weight\s*[—-]?\s*([^*]*(?:\*(?!\/)[^*]*)*)\*\//;
const MARKER_LINE =
  /ui-pattern:\s*heavy-weight\s*[—-]?\s*([^*\n]+(?:\n\s*(?:\/\/|\*)\s*[^*\n]+)*)/;
const MIN_REASON_WORDS = 5;
const LOOKBEHIND = 400;

/** Where the seven is retired: all-caps pressure, a heading, or small text. */
const UPPERCASE = /\buppercase\b/;
const TEXT_XS = /\btext-xs\b/;
const BOLD = /\bfont-bold\b/;
const HEADINGS = new Set(["h1", "h2", "h3"]);

export default {
  name: "heavy-weight",
  says:
    "`font-bold` (700) is retired outside monospace code, and three shapes are " +
    "always wrong: in a class with `uppercase`, on an `<h1>`–`<h3>`, or beside " +
    "`text-xs`. Each stacks a second layer of emphasis on a line that already " +
    "carries one — all-caps, a heading's size, a small label's tracking — and " +
    "the typography table gives that job to `font-semibold` (titles) or " +
    "`font-medium` (labels).",
  advice:
    "Titles take `font-semibold` (§11.2: page `text-xl`, card `text-lg`,\n" +
    "section `text-base`); labels take `font-medium` — form labels ALWAYS\n" +
    "(§1.2: NEVER `font-bold`). A monospace code may keep the seven where the\n" +
    "table's Code/mono row puts it, and a numeric tile where the figure is the\n" +
    "only content is outside this rule; when the weight is right for one of\n" +
    "those reasons at a site the rule still reads, write it down:\n" +
    "  {/* ui-pattern: heavy-weight — <why the seven carries information here> */}\n" +
    "The reason must be a sentence.",

  run(files) {
    const considered = new Set();
    const findings = [];

    for (const file of files) {
      const text = withoutComments(file.text);
      if (!BOLD.test(text)) continue;
      considered.add(file.path);

      for (const match of text.matchAll(/<[A-Za-z][A-Za-z0-9.]*/g)) {
        const start = match.index;
        const end = tagEnd(text, start);
        if (end === -1) continue;

        const tag = text.slice(start, end + 1);
        const className = classNameOf(tag);
        if (!className || !BOLD.test(className)) continue;

        const element = match[0].slice(1).toLowerCase();
        const inHeading = HEADINGS.has(element);
        if (!inHeading && !UPPERCASE.test(className) && !TEXT_XS.test(className))
          continue;
        if (excused(file.text, start)) continue;

        findings.push(`${file.path}:${lineAt(text, start)}`);
      }
    }

    return { considered: considered.size, findings };
  },
};

/**
 * Whether the site at `index` carries the marker.
 *
 * The scan runs on the comment-stripped copy, which blanks comments in place
 * rather than removing them — every offset still points at the same character
 * of the original, which is where the reason itself survives. The whole
 * comment has to close (`*` + `/`) for the JSX form: a line marker's reason
 * stops at its own newline, so a short one cannot feed on the code below it.
 */
function excused(original, index) {
  const before = original.slice(Math.max(0, index - LOOKBEHIND), index);
  for (const pattern of [MARKER, MARKER_LINE]) {
    pattern.lastIndex = 0;
    const reason = before.match(pattern)?.[1] ?? "";
    const words = reason
      .replace(/\/\/|\*|\{|\}/g, " ")
      .trim()
      .split(/\s+/)
      .filter(Boolean);
    if (words.length >= MIN_REASON_WORDS) return true;
  }
  return false;
}
