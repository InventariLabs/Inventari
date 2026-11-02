import { lineAt, openingTags } from "./lib.mjs";

/** The component whose whole job is to ask before destroying something. */
const CONFIRMATION_FILES = /(?:ConfirmDialog|ConfirmationDialog)\.tsx$/;

/**
 * The neutral variants a destructive action hides in. `default`/`primary`
 * are filled and therefore loud in their own way; the mistake this rule
 * reads is destruction dressed as an ordinary row action.
 */
const NEUTRAL_VARIANT = /variant="(ghost|outline|secondary|link)"/;

/**
 * A variant given as an expression is usually the state switch §2.13a
 * describes — destructive in one state only, switching variant with it
 * (`wf.is_active ? "ghostDanger" : "outline"`). A static read cannot judge
 * it, so it is skipped rather than guessed at.
 */
const EXPRESSION_VARIANT = /variant=\{/;

/**
 * The destructive act is read from the i18n key, never from the visible
 * text: the label is translated, the key is not. The last dotted segment
 * names the act (`common:actions.delete`, `recipes:image.delete`).
 */
const T_CALL = /(?:t|tDyn)\(\s*["'`]([^"'`${]+)["'`]/g;
const DESTRUCTIVE_WORDS = new Set([
  "delete",
  "remove",
  "deactivate",
  "archive",
  "discard",
  "destroy",
  "revoke",
  "decommission",
  "dispose",
  "retire",
  "scrap",
  "terminate",
  "unassign",
  "void",
]);

/**
 * The escape hatch, same shape as `filled-destructive`: a reason at the call
 * site, at least five words, in a comment just above.
 *
 *   {/* ui-pattern: destructive-as-neutral — this tile is the confirmation
 *       step itself; the danger colour would shout twice *\/
 */
const EXCEPTION = /ui-pattern:\s*destructive-as-neutral\s*[—-]?\s*([^*}]+)/;
const MIN_REASON_WORDS = 5;
const LOOKBEHIND = 500;

export default {
  name: "destructive-as-neutral",
  says:
    "A destructive action wearing a neutral variant gives no warning at " +
    "rest: the first signal arrives on tap, and on a touch screen hover " +
    "never comes — UI_GUIDELINES §2.13a. The filled variants are guarded " +
    "by destructive-outside-confirm; this is the other side of the same " +
    "mistake.",
  advice:
    'Use variant="ghostDanger" and put the divider between the safe ' +
    "actions and the destructive one:\n" +
    '<span aria-hidden="true" className="w-px h-5 shrink-0 bg-border mx-1" />',

  run(files) {
    const considered = new Set();
    const findings = [];

    for (const file of files) {
      if (CONFIRMATION_FILES.test(file.path)) continue;

      for (const { tag, index } of openingTags(file.text, "Button")) {
        if (!NEUTRAL_VARIANT.test(tag)) continue;
        if (EXPRESSION_VARIANT.test(tag)) continue;

        considered.add(file.path);

        const before = file.text.slice(Math.max(0, index - LOOKBEHIND), index);
        const reason = before.match(EXCEPTION)?.[1] ?? "";
        if (
          reason.trim().split(/\s+/).filter(Boolean).length >= MIN_REASON_WORDS
        )
          continue;

        // The label lives between the opening tag and `</Button>`; reading
        // from the tag's own start also catches icon-only buttons whose
        // destructive name sits in an `aria-label` prop.
        const close = file.text.indexOf("</Button>", index);
        const content =
          close === -1
            ? tag
            : file.text.slice(index, Math.min(close, index + 1000));

        T_CALL.lastIndex = 0;
        const destructive = [...content.matchAll(T_CALL)].some((m) =>
          DESTRUCTIVE_WORDS.has(m[1].split(".").pop()),
        );
        if (!destructive) continue;

        findings.push(`${file.path}:${lineAt(file.text, index)}`);
      }
    }

    return { considered: considered.size, findings };
  },
};
