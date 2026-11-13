import {
  lineAt,
  openingTags,
  sizeOf,
  withoutComments,
} from "./lib.mjs";

/**
 * The glyph sizes a button size may put beside its label (UI_GUIDELINES §6,
 * §11.4). A label button's icon is 16 — the size of its text line — with two
 * named exceptions: a small button (`text-xs`) may drop to 14, and a large one
 * (`text-base`, the prominent phone CTA) may rise to 20. Sizes that carry no
 * label (`icon`, `iconSm`, `inline`) are outside the rule.
 */
const SANCTIONED = {
  default: [16],
  md: [16],
  content: [16],
  row: [16],
  sm: [14, 16],
  contentSm: [14, 16],
  lg: [16, 20],
};

export default {
  name: "button-icon-size",
  says:
    "The icon in a Button's `leftIcon` / `rightIcon` is not a size its " +
    "button allows — 18 and 20 on a standard button, or 12/15 on a small " +
    "one, make the glyph and the label different heights in the same row " +
    "(UI_GUIDELINES §6, §11.4).",
  advice:
    "`size={16}` on a standard button. `size=\"sm\"` / `contentSm` takes 14 or\n" +
    "16, `size=\"lg\"` takes 16 or 20; nothing else. An icon-only button has its\n" +
    "own row in the table and is not read here.",

  run(files) {
    const considered = new Set();
    const findings = [];

    for (const file of files) {
      const text = withoutComments(file.text);
      for (const { tag, index } of openingTags(text, "Button")) {
        const { own, icons } = splitIcons(tag);
        if (icons.length === 0) continue;
        // A size chosen at runtime (`size={compact ? "sm" : "default"}`) has no
        // single answer to compare against.
        if (/\bsize=\{/.test(own)) continue;
        const allowed = SANCTIONED[sizeOf(own)];
        if (!allowed) continue;

        considered.add(file.path);
        if (icons.some((px) => !allowed.includes(px))) {
          findings.push(`${file.path}:${lineAt(text, index)}`);
        }
      }
    }

    return { considered: considered.size, findings };
  },
};

/**
 * The button's own attributes, and the numeric `size={…}` of every icon it
 * passes as `leftIcon` / `rightIcon`. The icon expressions are blanked out of
 * `own` so an icon's props are never read as the button's.
 */
function splitIcons(tag) {
  let own = tag;
  const icons = [];

  for (const slot of tag.matchAll(/\b(?:left|right)Icon=\{/g)) {
    const open = slot.index + slot[0].length - 1;
    let depth = 0;
    let end = -1;
    for (let i = open; i < tag.length; i++) {
      if (tag[i] === "{") depth++;
      else if (tag[i] === "}" && --depth === 0) {
        end = i;
        break;
      }
    }
    if (end === -1) continue;

    const expression = tag.slice(open, end + 1);
    for (const px of expression.matchAll(/\bsize=\{(\d+)\}/g)) {
      icons.push(Number(px[1]));
    }
    own = own.slice(0, slot.index) + " ".repeat(end + 1 - slot.index) + own.slice(end + 1);
  }

  return { own, icons };
}
