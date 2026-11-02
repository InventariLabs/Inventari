/**
 * The one look a field label has.
 *
 * `Input`, `Select`, `NativeSelect`, `Textarea` and `DateInput` each render
 * their own label from these classes; anything that has to place a label
 * itself — a control that owns its layout, a group of options with no single
 * field to point at — imports it instead of retyping the string, which is how
 * one form ended up with two label styles and two label-to-field gaps.
 */
export const FIELD_LABEL_CLASS =
  "block text-xs font-medium uppercase text-on-secondary ml-1 tracking-wide";

/**
 * The required-field star. Rendered inside the label but hidden from the
 * accessibility tree: requiredness travels via `required`/`aria-required` on
 * the control, so a screen reader says the field name and "required" — never
 * "star". Callers must not bake ` *` into the label string.
 */
export function RequiredStar() {
  return (
    <span aria-hidden="true" className="text-red-600 dark:text-red-400 ml-1">
      *
    </span>
  );
}
