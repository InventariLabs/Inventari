import { lineAt, openingTags } from "./lib.mjs";

/** The component whose whole job is to ask before destroying something. */
const CONFIRMATION_FILES = /(?:ConfirmDialog|ConfirmationDialog)\.tsx$/;

const FILLED_DESTRUCTIVE = /variant="(?:destructive|danger)"/;

/**
 * The escape hatch, and the price of using it.
 *
 * Some filled red buttons are right: the confirmation step a screen expands
 * into rather than opening a dialog for, the remove chip on a photo where a
 * ghost button would be invisible on whatever the photo happens to be. Those
 * are exceptions with a reason, not a baseline — a list of paths with no
 * argument attached is where a rule goes to be forgotten. So the reason lives
 * at the call site, in the shape the backend's architecture linter already
 * uses, and has to be an actual sentence.
 *
 *   {\/* ui-pattern: filled-destructive — this is the confirmation step, the
 *       reason field beside it is what makes it one *\/}
 */
const EXCEPTION = /ui-pattern:\s*filled-destructive\s*[—-]?\s*([^*}]+)/;
const MIN_REASON_WORDS = 5;
const LOOKBEHIND = 500;

export default {
  name: "destructive-outside-confirm",
  says:
    "A filled red button outside a confirmation dialog outweighs the row it " +
    "sits in: the eye lands on Delete before the name of the thing being " +
    "deleted — UI_GUIDELINES §2.13a reserves the filled variants for the " +
    "screen where destroying is the whole point.",
  advice:
    'In a row or a toolbar use variant="ghostDanger": the label carries the\n' +
    "warning at rest rather than on hover, which a touch screen never sends.\n" +
    "Keep the filled variant for the confirmation dialog's own action.",

  run(files) {
    const considered = new Set();
    const findings = [];

    for (const file of files) {
      if (CONFIRMATION_FILES.test(file.path)) continue;

      // `<Button>` only. A raw search of the file text reported the `variant`
      // prop of anything that takes one — `<ConfirmDialog variant="danger">`,
      // which is the rule's own exception, and `<Badge variant="danger">`,
      // which is a label and cannot be pressed at all. Two thirds of what this
      // rule first found was one of those two.
      for (const { tag, index } of openingTags(file.text, "Button")) {
        if (!FILLED_DESTRUCTIVE.test(tag)) continue;

        considered.add(file.path);

        const before = file.text.slice(Math.max(0, index - LOOKBEHIND), index);
        const reason = before.match(EXCEPTION)?.[1] ?? "";
        if (
          reason.trim().split(/\s+/).filter(Boolean).length >= MIN_REASON_WORDS
        )
          continue;

        findings.push(`${file.path}:${lineAt(file.text, index)}`);
      }
    }

    return { considered: considered.size, findings };
  },
};
