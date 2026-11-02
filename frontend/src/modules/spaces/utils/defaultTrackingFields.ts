/**
 * Default toggleable tracking fields for a freshly-created storage location.
 *
 * Storage is vertical-agnostic. We do NOT infer freeze_date from a name like
 * "Freezer" anymore — freeze_date is a category-level field, decided when the
 * user assigns a category to an item.
 *
 * Empty default is intentional: the wizard shows "name, quantity, unit" as
 * always-on (informational, no toggles) and lets the user opt into the
 * optional fields (barcode, price, notes, shelf_location) in step 3.
 */

import type { NeutralBaseFieldKey } from "./neutralBaseFields";

const EMPTY: readonly NeutralBaseFieldKey[] = Object.freeze([]);

export function defaultTrackingFieldsForLocation(
  _name: string,
): readonly NeutralBaseFieldKey[] {
  // The name argument is retained for API stability with the old
  // `defaultFieldsForName(name)` signature, but it is intentionally unused.
  void _name;
  return EMPTY;
}
