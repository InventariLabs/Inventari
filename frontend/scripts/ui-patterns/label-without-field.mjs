import {
  classNameAlternatives,
  classNameOf,
  lineAt,
  openingTags,
  withoutComments,
  withoutResponsive,
} from "./lib.mjs";

/**
 * A field nobody names.
 *
 * A label is the one element that carries a field's name into the
 * accessibility tree, and it does that in exactly two ways: `htmlFor` pointing
 * at the control's id, or the control sitting inside it. Written above a field
 * with neither, it is styled text — the field is announced without a name,
 * clicking the words focuses nothing, and the sighted reader is the only one
 * who sees a connection.
 *
 * The fix is rarely `htmlFor`. `Input`, `Select`, `NativeSelect`, `Textarea`
 * and `DateInput` render their own label from a `label` prop, with the id
 * already wired and one house style; a hand-rolled label beside them is how
 * one form ends up with two label styles and two label-to-field gaps.
 *
 * The second pass reads what the first cannot see: a control with no label
 * at all. The commonest field in this repo is one-`Input`-per-line, and the
 * shared component generates the id and wires `htmlFor` itself — so the
 * mistake that actually ships is the hand-built control beside that path:
 * a range slider, the trigger of a custom select, a field in a repeating
 * row, each with its visible label in a styled `<span>` or in no element at
 * all. A rule that opens only files containing `<label` is blind to exactly
 * those, so this pass walks every control and asks what names it.
 *
 * What counts as a name, in the order the fix prefers them: the house
 * components' `label` prop, `aria-label` / `aria-labelledby`, an enclosing
 * `<label>`, an `htmlFor` from this file pointing at the control's id. What
 * keeps a control OUT of the findings, because the name can live where a
 * single file cannot see it: a spread (`{...props}` can carry any of the
 * above in from the caller), and any `id` at all — the field renderers take
 * their id as a prop precisely so the parent can point its label at it.
 * `display: none` (`hidden` in every className alternative) is out of the
 * accessibility tree, so a hidden file input behind an upload button needs
 * no name; and a raw input of type hidden/submit/button/reset/image either
 * names itself or holds nothing to name.
 */

/** Controls that get their name from a label wrapped around them. */
const CONTROL =
  /<(input|select|textarea|Input|NativeSelect|Select|Textarea|Checkbox|DateInput|QuantityInput|SearchableCombobox|ProductCombobox)\b/;

const CONTROL_NAMES = [
  "input",
  "select",
  "textarea",
  "Input",
  "NativeSelect",
  "Select",
  "Textarea",
  "Checkbox",
  "DateInput",
  "QuantityInput",
  "SearchableCombobox",
  "ProductCombobox",
];

/** House components whose `label` prop renders a wired `<label>`. On a raw
 * element `label=` is an unknown attribute and names nothing. */
const LABEL_PROP_COMPONENTS = new Set(
  CONTROL_NAMES.filter((n) => n[0] === n[0].toUpperCase()),
);

/** Raw input types that carry their own name or hold nothing to name. */
const NAMELESS_RAW_TYPES = /\btype=["'](hidden|submit|button|reset|image)["']/;

/** A spread can carry `label`, `aria-label` or `id` in from the caller. */
const SPREAD = /\{\.\.\./;

/** `display: none` in every className alternative — out of the tree. */
function alwaysHidden(tag) {
  const className = classNameOf(tag);
  if (!className) return false;
  return classNameAlternatives(className).every((alt) =>
    /(?:^|\s)hidden(?:\s|$)/.test(withoutResponsive(alt)),
  );
}

export default {
  name: "label-without-field",
  says:
    "A `<label>` with no `htmlFor` and no control inside it names nothing — " +
    "and a control no label points at is announced without a name at all: " +
    "the field's purpose never reaches the accessibility tree, and clicking " +
    "the words focuses nothing.",
  advice:
    "Pass the text to the control's own `label` prop — Input, Select,\n" +
    "NativeSelect, Textarea and DateInput all render it with the id wired.\n" +
    "Where the layout puts the label beside the field rather than above it,\n" +
    "give the control an id and point `htmlFor` at it; a control whose\n" +
    "visible label belongs to a sibling (a filter on a control bar, a field\n" +
    "mirroring a slider) names itself with `aria-label` / `aria-labelledby`.\n" +
    "For a group of options with no single field to name, use ChoiceGroup,\n" +
    "which labels the group instead.",

  run(files) {
    const findings = [];

    for (const file of files) {
      const text = withoutComments(file.text);

      const labels = openingTags(text, "label").map(({ tag, index }) => ({
        tag,
        index,
        close: text.indexOf("</label>", index + tag.length),
      }));

      // First pass — a label that names nothing.
      for (const { tag, index, close } of labels) {
        if (tag.includes("htmlFor=")) continue;
        if (close === -1) continue;
        if (CONTROL.test(text.slice(index + tag.length, close))) continue;
        findings.push(`${file.path}:${lineAt(text, index)}`);
      }

      // Second pass — a control nothing names, in a file that may hold no
      // `<label>` element at all.
      const wrapped = (i) =>
        labels.some(
          ({ index, close }) => close !== -1 && i > index && i < close,
        );

      for (const control of CONTROL_NAMES) {
        for (const { tag, index } of openingTags(text, control)) {
          if (control === "input" && NAMELESS_RAW_TYPES.test(tag)) continue;
          if (SPREAD.test(tag)) continue;
          if (alwaysHidden(tag)) continue;
          if (tag.includes("aria-label=") || tag.includes("aria-labelledby="))
            continue;
          // ProductCombobox turns its placeholder into the control's
          // accessible name when no label is set (the input inside it reads
          // `aria-label={label ? undefined : placeholder}`) — so at a call
          // site, a placeholder IS the name.
          if (control === "ProductCombobox" && /\bplaceholder=/.test(tag))
            continue;
          if (LABEL_PROP_COMPONENTS.has(control) && /\blabel=/.test(tag))
            continue;
          if (wrapped(index)) continue;
          if (/\bid=/.test(tag)) continue;
          findings.push(`${file.path}:${lineAt(text, index)}`);
        }
      }
    }

    return { considered: files.length, findings: [...new Set(findings)] };
  },
};
