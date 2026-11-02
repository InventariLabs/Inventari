import { classNameOf, lineAt, openingTags, withoutComments } from "./lib.mjs";

/** The one size a disclosure indicator is drawn at (UI_GUIDELINES §2.10). */
const INDICATOR_SIZE = 18;

/** The layer that owns control chrome — §2.0, "who owns which class". */
const DESIGN_SYSTEM = /^components\/ui\//;

/**
 * The heights §2.10 allows a control: the shared scale, the one compact
 * variant, and a `calc()` of them for a control whose border sits on a wrapper.
 */
const CONTROL_HEIGHT = /(?:min-)?h-(?:9|10|11|\[calc\()/;

/** How far back a chevron's own control can be. */
const LOOKBEHIND = 1200;

/** Things a disclosure indicator can hang off. */
const TRIGGER = /<(?:button|select)\b|<[A-Za-z.]*Trigger\b/g;

/**
 * Everything from the chevron's own control down to the chevron — the slice
 * that has to state a height. Null when no control is in reach, which is what
 * a chevron used as decoration looks like.
 */
function triggerBefore(text, index) {
  const from = Math.max(0, index - LOOKBEHIND);
  let last = null;
  for (const m of text.slice(from, index).matchAll(TRIGGER)) last = m;

  return last === null ? null : text.slice(from + last.index, index);
}

export default {
  name: "disclosure-indicator",
  says:
    "A control that opens something draws the platform's arrow, or draws " +
    "lucide's at a size of its own — so one form column shows two or three " +
    "different indicators. UI_GUIDELINES §2.10 gives them one: ChevronDown at " +
    `${INDICATOR_SIZE}, at the trailing edge, on a control of the shared ` +
    "height.",
  advice:
    "On a native <select>, add `appearance-none` and `pr-10` and draw the\n" +
    "chevron yourself — the control stays native, so a phone keeps opening\n" +
    "the system picker, but the indicator stops depending on the OS.\n" +
    "A section header that reads as a control takes the §2.10 height too.",

  run(files) {
    const considered = new Set();
    const findings = [];

    for (const file of files) {
      const text = withoutComments(file.text);

      // A bare `<select>` renders whatever arrow the OS and the browser agree
      // on, next to whatever the app draws. Anywhere in the corpus, not just
      // in the design system: this is the one shape no call site may spell.
      for (const { tag, index } of openingTags(text, "select")) {
        considered.add(file.path);
        if (!/\bappearance-none\b/.test(classNameOf(tag) ?? ""))
          findings.push(`${file.path}:${lineAt(text, index)}`);
      }

      // The size and the control under it are guarded in the design system
      // only. A chevron on a card row or a tree node is a different element —
      // §2.10 is about form controls, and a rule that claimed the rest would
      // be asserting something nobody has decided.
      if (!DESIGN_SYSTEM.test(file.path)) continue;

      for (const { tag, index } of openingTags(text, "ChevronDown")) {
        considered.add(file.path);

        const size = tag.match(/size=\{(\d+)\}/)?.[1];
        if (Number(size) !== INDICATOR_SIZE) {
          findings.push(`${file.path}:${lineAt(text, index)}`);
          continue;
        }

        const trigger = triggerBefore(text, index);
        if (trigger && !CONTROL_HEIGHT.test(trigger))
          findings.push(`${file.path}:${lineAt(text, index)}`);
      }
    }

    return { considered: considered.size, findings };
  },
};
