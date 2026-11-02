const FOCUSABLE =
  'input:not([type="hidden"]):not([disabled]), select:not([disabled]), textarea:not([disabled]), button:not([disabled]), [tabindex]:not([tabindex="-1"])';

/**
 * Moves focus to the first field of the form that has an error, scrolling it
 * into view.
 *
 * A refused submit used to do nothing the reader could see when the field
 * sat below the fold: no request, no toast, focus left on the button. Fields
 * mark their wrapper with `data-field-key`; the first one in the page, in
 * reading order, whose key is among *keys* gets the focus.
 */
export function focusFirstInvalidField(
  keys: Iterable<string>,
  root: ParentNode = document,
): boolean {
  const invalid = new Set(keys);
  for (const wrapper of root.querySelectorAll<HTMLElement>(
    "[data-field-key]",
  )) {
    if (!invalid.has(wrapper.dataset.fieldKey ?? "")) continue;
    const target = wrapper.querySelector<HTMLElement>(FOCUSABLE);
    if (!target) continue;
    target.focus();
    target.scrollIntoView?.({ block: "center" });
    return true;
  }
  return false;
}
