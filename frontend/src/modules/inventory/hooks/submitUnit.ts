import type { FieldDefinition, ItemCreate } from "@/types";
import type { ItemFormData } from "./useItemForm";

/** The errors the form's own rules find, keyed the way the fields are. */
export function requiredFieldErrors(
  fieldDefinitions: FieldDefinition[],
  formData: ItemFormData,
  requiredMessage: string,
): Record<string, string> {
  const errors: Record<string, string> = {};
  fieldDefinitions
    .filter((f) => f.visible && f.required)
    .forEach((field) => {
      const value = field.is_custom
        ? formData.metadata?.[field.key]
        : formData[field.key as keyof ItemFormData];
      if (!value || (typeof value === "string" && !value.trim())) {
        errors[field.key] = requiredMessage;
      }
    });
  return errors;
}

/**
 * What the unit on this payload has to say for itself.
 *
 * The server refuses a unit that contradicts the matched product template's
 * unless the request confirms the choice, and the form has already asked —
 * so all that is left is to say which case this is. The template's own unit
 * is not a choice: sending it back would turn the server's own answer into
 * something the reader decided, so it leaves the payload instead.
 *
 * Returns the payload with the unit settled, so the caller has one object to
 * send rather than a rule to remember.
 */
export function settleUnitOnPayload(
  submission: Partial<ItemCreate>,
  chosenUomId: string | undefined,
  context: {
    /** The matched template's unit, when the catalogue knows the product. */
    templateUomId: string | null;
    /** Whether this is a confirmed choice, as `useUnitChoice` reports it. */
    isConfirmedChoice: (uomId: string | undefined) => boolean;
    /** The unit the record already carries — what a change is read against. */
    initialUomId: string | undefined;
  },
): Partial<ItemCreate> {
  const { templateUomId, isConfirmedChoice, initialUomId } = context;

  if (templateUomId) {
    if (chosenUomId === templateUomId) {
      delete submission.uom_id;
    } else if (isConfirmedChoice(chosenUomId)) {
      submission.unit_confirmed_over_template = true;
    }
    return submission;
  }

  // No matched template means no catalogue answer to differ from — but an
  // edit that moves the record onto another unit is the same deliberate
  // choice, and the server asks the same question about it. The reader
  // answered it by making the change; there is nothing left to show them, so
  // the confirmation travels without a dialog. A record holding stock never
  // reaches the server's unit guard at all — it is refused, and argues the
  // case with the stock-unit sentence.
  if (chosenUomId && initialUomId && chosenUomId !== initialUomId) {
    submission.unit_confirmed_over_template = true;
  }
  return submission;
}
