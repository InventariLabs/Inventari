import {
  classNameOf,
  lineAt,
  openingTagsWithParent,
  withoutResponsive,
} from "./lib.mjs";

/**
 * A class is a token, not a substring: `\bflex\b` also matches the head of
 * `flex-col`, and `flex-1` ends where `flex-10` begins. Boundaries are the
 * characters a className can actually join tokens with.
 */
const TOKEN = (klass) => new RegExp(`(?:^|[\\s\`'\"])${klass}(?=$|[\\s\`'\"])`);

/** A flex container states its display; a direction alone does nothing. */
const FLEX_DISPLAY = TOKEN("(?:inline-)?flex");
/** The base (unmodified) direction — the one in force below the first `sm:`. */
const COLUMN_DIRECTION = TOKEN("flex-col(?:-reverse)?");
/**
 * The base `flex-1`, and `basis-0` on its own. Measured on a 44px button in a
 * column with no height: `flex-1` and `grow basis-0` both render 21px, and
 * so does `basis-0` alone — the zero basis is what throws the pinned height
 * away, `grow` only decides where the freed space goes. `grow` alone keeps
 * 44px and is not a stake. `flex-auto` is not here either: its basis is
 * `auto`, which keeps the height the variant pins (measured, 44px).
 */
const FLEX_FILL = TOKEN("(?:flex-1|basis-0)");
/**
 * A max-width variant describes the narrow screen itself — `max-sm:flex-col`
 * is the phone column the base `flex-col sm:flex-row` spells from the other
 * end of the breakpoint. Min-width variants are left to `withoutResponsive`:
 * they describe bigger screens, where the collapse this rule guards does not
 * press.
 */
const MAX_WIDTH_VARIANT = /(?:^|[\s`'"])max-[a-z0-9]+:([^\s`'"]+)/g;
/**
 * A definite height gives the fill a box: `h-*` or a floor `min-h-*` that
 * names a real length. The values that only look like one are refused, each
 * measured to leave the 18px collapse standing: `auto`, `fit`, `min`, `max`
 * (intrinsic sizes), and the zero lengths `0`, `px` and `[0…]` (`[0px]`,
 * `[0vh]`, `[0%]`). `min-h-0` is permission to shrink, not a height, and a
 * bare `max-h-*` only caps — both leave the collapse standing.
 */
const NOT_A_HEIGHT =
  "(?:auto|fit|min|max|0|px|\\[0(?:\\.0+)?[a-z%]*\\])(?=$|[\\s`'\"])";
const DEFINITE_HEIGHT = new RegExp(
  `(?:^|[\\s\`'"])(?:h-(?!${NOT_A_HEIGHT})|min-h-(?!${NOT_A_HEIGHT}))[^\\s\`'"]+`,
);

/** The classes a parent holds outside every responsive variant. */
const narrowState = (className) =>
  [...className.matchAll(MAX_WIDTH_VARIANT)].map((m) => m[1]).join(" ");

export default {
  name: "flex-1-in-a-column",
  says:
    "A button with a zero flex-basis (`flex-1`, `basis-0`, `grow basis-0`) " +
    "inside a flex row that is a column below `sm` — written as base " +
    "`flex flex-col sm:flex-row` or as the max-width variant `max-sm:flex-col` " +
    "— stakes the button's height on that column: flex-basis 0% becomes the " +
    "size along the main axis, displacing the height the size variant pins, " +
    "and a parent with no height of its own shrinks the button to its text " +
    "row — 20px where the variant promises 44. The phone, where the button " +
    "is pressed with a finger, is exactly the width that collapses.",
  advice:
    "Let the width carry the fill instead of the flex line: `w-full sm:w-auto`\n" +
    "keeps the phone full-width and the desktop intrinsic, which is what the\n" +
    "footer rows built on <SheetActions> already do. In a column `flex-1` is\n" +
    "a height claim; in a row it is a width one — say which you meant. When\n" +
    "the fill into a column is what you want, state the column's height in\n" +
    "its own className (`h-*`, `min-h-*`): the box a reader looks for to read\n" +
    "the intent is the box this rule reads.",

  // Named limits of the rule, measured on the corpus: a parent
  // whose className is built by cn()/clsx() or a variable is deliberately
  // given up on rather than guessed at, and a Button wrapped in another
  // component hides its fill class from this walk. The reverse case — a
  // child of an actions row that must keep its own width — is documented on
  // <SheetActions> and said with `!flex-none`. (A plain <div> or grid
  // parent is correctly passed: the button is not a flex item there.)
  //
  // Decision on scope, standing: scripts/ stays outside ESLint.
  // The pattern files are lint code themselves, and every detector in the
  // BLOCKING set has its own vitest file (`index.test.mjs` pins that). The
  // reason does not stretch to the gate entry points: nine of them have no
  // spec (listed in eslint.config.js), so there the exclusion rests only on
  // nothing in scripts/ being shipped. A dead import in a detector is this
  // harness's to catch, which is how the one found while writing this rule
  // was found: by reading, then deleted here.

  run(files) {
    const considered = new Set();
    const findings = [];

    for (const file of files) {
      for (const {
        tag,
        index,
        parentClassName,
        parentClassNameIsLiteral,
      } of openingTagsWithParent(file.text, "Button")) {
        const className = classNameOf(tag);
        const base = withoutResponsive(className ?? "");
        if (!FLEX_FILL.test(base)) continue;

        considered.add(file.path);

        // The button is a flex item of its direct parent and of nothing
        // further out, so the parent has to be read to be blamed: a className
        // built by `cn(...)` only maybe holds the classes its text shows, and
        // a rule that guesses reports correct code.
        if (!parentClassNameIsLiteral) continue;
        const parent = withoutResponsive(parentClassName);
        const narrow = narrowState(parentClassName);

        // The column this rule guards is the narrow one: base direction, or
        // the direction a max-width variant names for the phone. A column in
        // a max-width variant claims the narrow layout by construction; a
        // base one only counts where a display class makes it a container.
        const columnClaimed =
          COLUMN_DIRECTION.test(narrow) ||
          (COLUMN_DIRECTION.test(parent) &&
            (FLEX_DISPLAY.test(parent) || FLEX_DISPLAY.test(narrow)));
        if (!columnClaimed) continue;

        // A definite height turns the fill from a stake into a deliberate
        // fill of a known box — `flex flex-col h-64` is a legal home for
        // `flex-1`. The height counts where the column counts: stated on the
        // parent itself or under the same max-width variant.
        if (DEFINITE_HEIGHT.test(parent) || DEFINITE_HEIGHT.test(narrow))
          continue;
        findings.push(`${file.path}:${lineAt(file.text, index)}`);
      }
    }

    return { considered: considered.size, findings };
  },
};
