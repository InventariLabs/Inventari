import {
  classNameAlternatives,
  lineAt,
  openingTags,
  tagEnd,
  withoutComments,
} from "./lib.mjs";

/**
 * A control with nothing to call it.
 *
 * A button whose whole content is an SVG has no text to announce. A screen
 * reader says "button" and stops; a keyboard user tabbing along a row of them
 * cannot tell the reversible action from the one that takes the record off the
 * list. `title` is the usual half-measure — it never appears on a touch screen
 * and some readers skip it — so the name has to be an `aria-label`.
 *
 * The rule used to ask the button what size it had declared. That is the
 * spelling of the mistake, not the mistake: `<Button size="sm">` with a single
 * `<Lock />` inside is exactly as unannounced as `<Button size="icon">`, and
 * eight of them sat on the periods screen without ever entering the candidate
 * set. So the size test is now one half of a union, and the other half reads
 * what the button actually contains.
 */

const ICON_SIZES = /size=\{?["']?(icon|iconSm|iconLg)["']?\}?/;
const HAS_NAME = /aria-label=|aria-labelledby=/;

/** Where the button's own text is the name — nothing icon-only about it. */
const HAS_TEXT_CHILD = /leftIcon=|rightIcon=/;

/** JSX spacing, and the `{ }` a stripped comment leaves behind. */
const EMPTY_EXPRESSION = /\{\s*\}|\{\s*["'`]\s*["'`]\s*\}/g;

/**
 * The children of the opening tag at `index`, or null when it is self-closing.
 *
 * Nested `<Button>`s are counted so a button wrapping another one — a row
 * action inside a card that is itself a button — reads its own children.
 */
function childrenOf(text, index, tag) {
  if (tag.endsWith("/>")) return "";

  const start = index + tag.length;
  let depth = 1;
  let cursor = start;

  while (depth > 0) {
    const open = text.indexOf("<Button", cursor);
    const close = text.indexOf("</Button>", cursor);
    if (close === -1) return null;
    if (open !== -1 && open < close) {
      depth++;
      cursor = open + 7;
      continue;
    }
    depth--;
    if (depth === 0) return text.slice(start, close);
    cursor = close + 9;
  }
  return null;
}

/**
 * Everything in `children` that is not tag markup.
 *
 * Walked rather than matched. A regex for "an element" either stops at the
 * first `>` inside an attribute or, made lazy, swallows a `<span>` up to the
 * `/>` of the icon after it — which is how the first run of this rule claimed
 * the language switcher, a button whose visible text sits in that span.
 */
function textOutsideTags(children) {
  let out = "";
  let i = 0;

  while (i < children.length) {
    if (children[i] === "<") {
      const end = tagEnd(children, i);
      if (end === -1) return out + children.slice(i);
      i = end + 1;
      continue;
    }
    out += children[i];
    i++;
  }
  return out;
}

/** What is left once the words would have been: brackets and separators. */
const SCAFFOLDING = /[(){}[\],;]|\s+/g;

/** Beyond this the branch expansion gives up, and so does the rule. */
const MAX_ALTERNATIVES = 8;

/**
 * Whether the children amount to nothing a reader could hear.
 *
 * The icons go with the markup; anything left — a `{t("…")}` call, a word, an
 * identifier that might resolve to a word — is treated as text.
 *
 * A ternary is read branch by branch rather than as one string, because the
 * commonest icon-only button in this repo is a toggle: `{expanded ?
 * <ChevronUp /> : <ChevronDown />}`. Judged whole it keeps the condition's
 * name and looks like text; judged per branch both sides are empty and it is
 * what it plainly is. The same button written twice, once for each layout,
 * was how this came up — the mobile copy declared an icon size and was
 * caught, the desktop one did not and was not.
 *
 * The rule still claims only what it is sure of: an expression it cannot
 * expand keeps the button out of the findings rather than into them.
 */
function isIconOnly(children) {
  const bare = textOutsideTags(children).replace(EMPTY_EXPRESSION, "");
  const branches = classNameAlternatives(bare);
  if (branches.length >= MAX_ALTERNATIVES) return false;
  return branches.every((branch) => branch.replace(SCAFFOLDING, "") === "");
}

export default {
  name: "icon-button-unnamed",
  says:
    "An icon-only button carries no text, so without `aria-label` it is " +
    'announced as "button" and nothing else. `title` does not stand in for ' +
    "it: touch screens never show it and several readers ignore it.",
  advice:
    "Give the control an aria-label with the same words the tooltip uses.\n" +
    "When the button is disabled for a reason, put that reason in the label\n" +
    "and on the screen — a tooltip is invisible to a finger.",

  run(files) {
    const considered = new Set();
    const findings = [];

    for (const file of files) {
      const text = withoutComments(file.text);

      for (const { tag, index } of openingTags(text, "Button")) {
        const declaresIconSize = ICON_SIZES.test(tag);
        const children = childrenOf(text, index, tag);
        const iconOnly = children !== null && isIconOnly(children);

        if (!declaresIconSize && !iconOnly) continue;
        considered.add(file.path);

        if (HAS_NAME.test(tag)) continue;
        // The size half keeps the guard it was written with: a button that
        // declares an icon size and hands its content to `leftIcon` has text
        // beside the icon. The content half needs no such guess.
        if (!iconOnly && HAS_TEXT_CHILD.test(tag)) continue;

        findings.push(`${file.path}:${lineAt(text, index)}`);
      }
    }

    return { considered: considered.size, findings: findings.sort() };
  },
};
