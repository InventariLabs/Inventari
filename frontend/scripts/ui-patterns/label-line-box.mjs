import { classNameOf, lineAt, openingTags, withoutComments } from "./lib.mjs";

/**
 * Class tokens that settle a `<label>`'s display box for it.
 *
 * `block` is the answer this rule wants; the rest are labels doing something
 * other than sitting above a field — a flex row wrapping a checkbox and its
 * text, a visually hidden label, one pulled out of flow. None of them is the
 * mistake, so none of them is reported.
 */
const SETTLES_DISPLAY =
  /\b(block|flex|inline-flex|inline-block|grid|inline-grid|hidden|sr-only|absolute|fixed|contents|table-cell)\b/;

/**
 * The classes behind `className={fieldLabel}`.
 *
 * A form that repeats the same label six times names the string once, and a
 * rule that only reads literals then judges the file by the one label written
 * inline — `BasicInfoSection` carries `block` in its constant and would have
 * been reported five times for labels that are already right. Same-file
 * `const NAME = "…"` only: anything imported is another file's business.
 */
function resolveConstant(text, name) {
  if (!/^[A-Za-z_$][\w$]*$/.test(name)) return null;

  const declaration = new RegExp(
    `\\bconst\\s+${name}\\s*(?::[^=]+)?=\\s*\\n?\\s*"([^"]*)"`,
  );
  return text.match(declaration)?.[1] ?? null;
}

/**
 * The one label constant that is *not* another file's business.
 *
 * `FIELD_LABEL_CLASS` exists so that a control owning its own layout draws
 * the shared label instead of retyping the string — the guidelines say to
 * import it. Judging a caller by the literal it did not write reported the
 * files that followed the rule and stayed quiet about the ones that did not.
 *
 * Read from the file rather than assumed: drop `block` from the shared class
 * and every caller should be reported, which is the point.
 */
const SHARED_LABEL_CLASS = "FIELD_LABEL_CLASS";

function sharedLabelClasses(files) {
  for (const file of files) {
    if (!file.path.endsWith("components/ui/fieldLabel.tsx")) continue;
    return resolveConstant(file.text, SHARED_LABEL_CLASS);
  }
  return null;
}

export default {
  name: "label-line-box",
  says:
    "A `<label>` with no display class is inline, so it sits in a line box " +
    "sized by the wrapper's inherited line-height rather than by the text — " +
    "about 8px taller than the label the shared controls render. In a grid " +
    "row the hand-labelled field ends up that much lower than the DateInput " +
    "or Select beside it, and nothing in the markup says why.",
  advice:
    "Pass the text to the control instead: `Input`, `Textarea`, `Select`,\n" +
    "`NativeSelect`, `DateInput` and `SearchableCombobox` all take a `label`\n" +
    "prop that puts it in the same wrapper, wires `htmlFor`, and keeps the\n" +
    "label-to-field gap identical everywhere. Where the control is not one of\n" +
    "those, add `block` to the label.",

  run(files) {
    const considered = new Set();
    const findings = [];
    const shared = sharedLabelClasses(files);

    for (const file of files) {
      const text = withoutComments(file.text);

      for (const { tag, index } of openingTags(text, "label")) {
        considered.add(file.path);

        const className = classNameOf(tag);
        const name = className?.trim();
        const classes = className
          ? (resolveConstant(text, name) ??
            (shared && name === SHARED_LABEL_CLASS ? shared : null) ??
            className)
          : null;
        if (classes && SETTLES_DISPLAY.test(classes)) continue;

        findings.push(`${file.path}:${lineAt(text, index)}`);
      }
    }

    return { considered: considered.size, findings };
  },
};
