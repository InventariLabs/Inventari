import type { FieldDefinition, ItemCreate } from "@/types";

/**
 * Fields that carry the record's identity rather than a detail of it: the API
 * takes them as values, never as `null`. The form refuses to submit without
 * them, so an empty one here is a bug upstream, not a request to clear.
 */
const NEVER_CLEARED = new Set(["name", "quantity", "location_id", "metadata"]);

export function buildSubmissionPayload(
  formData: Record<string, unknown>,
  fieldDefinitions: FieldDefinition[],
  /**
   * Whether this payload edits a record that already exists.
   *
   * It decides what an empty optional field means, and there is no reading
   * that works for both: on a new product an empty field was never filled in,
   * on an existing one it was emptied on purpose. Dropping the key — the only
   * behaviour there used to be — made clearing a category, a brand or a date
   * impossible while the form still reported the save as done.
   */
  mode: "create" | "update" = "create",
): Partial<ItemCreate> {
  const submission: Record<string, unknown> = { ...formData };

  const quantityNum = submission.quantity ? Number(submission.quantity) : 0;
  submission.quantity = quantityNum || 0;

  // The form's weight field holds the weight of a single unit; the API keeps
  // it on the product template and computes the line total (ADR-015).
  const unitWeight = submission.weight ? Number(submission.weight) : null;
  delete submission.weight;
  if (unitWeight !== null && !isNaN(unitWeight)) {
    submission.weight_value = unitWeight;
  } else if (mode === "update") {
    // Emptied, and the unit goes with it: a weight unit on a product with no
    // weight is a leftover, not a fact.
    submission.weight_value = null;
    submission.weight_uom_id = null;
  } else {
    delete submission.weight_uom_id;
  }

  if (submission.purchase_price)
    submission.purchase_price = Number(submission.purchase_price);

  Object.keys(submission).forEach((key) => {
    const value = submission[key];
    // `undefined` is the form not having the field at all — nothing was
    // emptied, so there is nothing to say about it.
    if (value === undefined) {
      delete submission[key];
      return;
    }
    if (value !== "" && value !== null) return;
    if (mode === "update" && !NEVER_CLEARED.has(key)) {
      submission[key] = null;
    } else {
      delete submission[key];
    }
  });

  fieldDefinitions
    .filter((f) => f.is_custom === false)
    .forEach((field) => {
      // A hidden field is one this profile does not ask about, which is not
      // the same as one the reader emptied: it leaves the payload entirely,
      // and whatever the record holds stays put.
      //
      // Barcode is the one exception, and a narrow one: the quick-add form
      // renders no input for it at all, so its only way in is handed to the
      // form before the first render — `?barcode=` carried from a scan. The
      // user could neither see it nor empty it, and dropping it silently
      // lost the instruction. Every other hidden field (category_id, say)
      // is seeded by the form's own memory and defaults, which the profile
      // hiding the field has every right to keep out of the payload.
      const handedOnCreate =
        mode === "create" &&
        field.key === "barcode" &&
        typeof submission.barcode === "string" &&
        submission.barcode !== "";
      if (!field.visible && !handedOnCreate) {
        delete submission[field.key];
        // The unit weight travels under a different name than its field.
        if (field.key === "weight") {
          delete submission.weight_value;
          delete submission.weight_uom_id;
        }
      }
    });

  if (submission.metadata) {
    const hiddenCustomKeys = new Set(
      fieldDefinitions
        .filter((f) => !f.visible && f.is_custom !== false)
        .map((f) => f.key),
    );

    const meta = submission.metadata as Record<string, unknown>;
    submission.metadata = Object.fromEntries(
      Object.entries(meta).filter(([key]) => !hiddenCustomKeys.has(key)),
    );

    if (
      Object.keys(submission.metadata as Record<string, unknown>).length === 0
    ) {
      delete submission.metadata;
    }
  }

  delete submission.uom;
  delete submission.template;

  return submission as Partial<ItemCreate>;
}
