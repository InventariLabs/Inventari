import { classNameOf, lineAt, openingTags } from "./lib.mjs";

/**
 * The form controls that render a wrapper around themselves.
 *
 * Each is a label, a control and an error message inside a `w-full` box, and
 * each takes two class props: `className` for the control, `wrapperClassName`
 * for the box.
 */
const FIELDS = [
  "Input",
  "Textarea",
  "Select",
  "NativeSelect",
  "DateInput",
  "SearchableCombobox",
];

/**
 * Classes that describe the box, not the control.
 *
 * Width, the share of a flex or grid row, and the space around it are all
 * measured against the field's siblings — they are the wrapper's business.
 * `w-full` is not here: it is what the control already is, so writing it
 * again is redundant rather than wrong.
 *
 * The leading group is the variant prefix, and it is the part worth spelling
 * out: `xs:w-16` is as much the box's business as `w-16`, and a rule that
 * only reads the bare form finds the field that carries both and misses the
 * one that carries only the responsive half.
 */
const BOX_CLASS =
  /^(?:[a-z0-9-]+:)*(?:(?:max-|min-)?w-(?!full$)\S+|flex-(?:1|none|initial|auto)|basis-\S+|(?:col|row)-span-\S+|m[trblxy]?-\S+|self-\S+)$/;

export default {
  name: "field-box-class",
  says:
    "A width or a margin in a form control's `className` lands on the control " +
    "and not on the box around it, so the box keeps its own full width and " +
    "the field looks unchanged — a `max-w-md` on a Textarea narrows the " +
    "textarea inside a wrapper still spanning the row.",
  advice:
    "Move it to `wrapperClassName`. `className` describes the control —\n" +
    "height, padding, font, colour; `wrapperClassName` describes the box the\n" +
    "field occupies among its siblings.",

  run(files) {
    const considered = new Set();
    const findings = [];

    for (const file of files) {
      for (const field of FIELDS) {
        for (const { tag, index } of openingTags(file.text, field)) {
          const className = classNameOf(tag);
          if (!className) continue;

          considered.add(file.path);
          const tokens = className.split(/\s+/).filter(Boolean);
          if (!tokens.some((token) => BOX_CLASS.test(token))) continue;

          findings.push(`${file.path}:${lineAt(file.text, index)}`);
        }
      }
    }

    return { considered: considered.size, findings };
  },
};
