import { classNameOf, lineAt, openingTags } from "./lib.mjs";

/**
 * A row that says what it is. Nothing else has to confirm it — these
 * components exist only to be the action bar of a dialog or a pinned page
 * footer, and a hand-written width inside one is a call site working around
 * the very thing it asked for.
 */
const NAMED_FOOTER = /(?:SheetFooter|SheetActions|DialogFooter|ModalFooter)/;

/**
 * A row that only looks like a footer — and half of these are not one.
 *
 * `border-t` alone reports a card's own action row, and inside a card in a
 * grid two buttons sharing the width is the right answer. So a row recognised
 * this way has to be shown to span something wide: an overlay, or a footer
 * pinned to the bottom of a page. What makes the split wrong is the width
 * being split.
 */
const FOOTER_SHAPE = /(?:border-t|justify-end|sticky\s+bottom)/;
const WIDE_SURFACE = /<(?:Sheet|ModalShell|Dialog)\b/;
const PINNED = /(?:shrink-0|flex-shrink-0|sticky|fixed)/;

/** How far back to look for that context — a footer's own opening tag. */
const LOOKBEHIND = 600;

/**
 * The footer nobody marked: in an overlay, a bare `flex gap-N` row whose own
 * children are two or more buttons. It carries no border, no `justify-end`
 * and no component name, so the shapes above cannot see it — it is the row
 * `flex-1` was written for when a dialog's buttons were first laid out. A
 * button beside an input or a cell that takes the slack is not this: the row
 * must hold nothing but buttons.
 */
function isBareButtonRow(text, index) {
  const start = text.lastIndexOf('<div className="', index);
  if (start < 0) return false;
  const end = text.indexOf("</div>", index);
  if (end < 0) return false;
  const row = text.slice(start, end);
  const open = row.slice(0, row.indexOf(">") + 1);
  if (!/\bflex\b/.test(open) || /\bgrid\b|flex-col/.test(open)) return false;
  // A tinted or bordered pill holding buttons is a segmented control: its
  // buttons share the width on purpose.
  if (/\b(?:bg-|rounded|border)/.test(open)) return false;
  const inner = row.slice(open.length);
  if (/<(?:div|Input|input|Select|SearchableCombobox)\b/.test(inner))
    return false;
  return (inner.match(/<Button\b/g) ?? []).length >= 2;
}

/** A narrowing that lets the button keep its intrinsic width on desktop. */
const RELEASED =
  /(?:sm|md|lg):(?:flex-none|flex-initial|w-auto|grow-0|flex-\[0)/;

export default {
  name: "footer-half-width",
  says:
    "A footer button with `flex-1` and nothing releasing it above `sm` splits " +
    "the dialog in half on a desktop, so Save and Delete carry the same visual " +
    "weight across the full width — UI_GUIDELINES §4.3 asks for full width on a " +
    "phone and intrinsic width from `sm:` up.",
  advice:
    "Put the buttons in <SheetActions> and delete the width from the call\n" +
    "site — the row states both halves of the rule. Full-width 50/50 is the\n" +
    "phone layout, not the desktop one.",

  run(files) {
    const considered = new Set();
    const findings = [];

    for (const file of files) {
      const inOverlay = WIDE_SURFACE.test(file.text);

      for (const { tag, index } of openingTags(file.text, "Button")) {
        const className = classNameOf(tag);
        if (!className || !/\bflex-1\b/.test(className)) continue;

        considered.add(file.path);
        if (RELEASED.test(className)) continue;

        // `flex-1` is right in plenty of rows that are not footers — a search
        // field beside a filter button, a cell that should take the slack.
        const before = file.text.slice(Math.max(0, index - LOOKBEHIND), index);
        const isFooter =
          NAMED_FOOTER.test(before) ||
          (FOOTER_SHAPE.test(before) && (inOverlay || PINNED.test(before))) ||
          (inOverlay && isBareButtonRow(file.text, index));
        if (!isFooter) continue;

        findings.push(`${file.path}:${lineAt(file.text, index)}`);
      }
    }

    return { considered: considered.size, findings };
  },
};
