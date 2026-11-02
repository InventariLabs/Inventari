import { usePartnerPicker } from "@/hooks/usePartnerPicker";
import { CUSTOMER_ROLE_TYPES, SUPPLIER_ROLE_TYPES } from "@/hooks/partnerRoles";

/**
 * The partner dropdown is filtered to the role set the document type
 * requires (supplier set for receipts, customer set for deliveries) and to
 * active partners only — the backend enforces the same rule on save. The OUT
 * dropdown is intentionally narrower than the backend: returns to suppliers
 * copy the partner from the source document.
 *
 * `selectedOffered` is whether the partner already chosen is one this picker
 * could offer; a form reads a chosen partner the picker cannot show as the
 * empty field the reader sees.
 */
export function useDocumentPartnerOptions(
  doc: { type?: string; partner_id?: string | null } | undefined,
  /** The partner held in a form, when it is not the document's saved one. */
  selectedId = doc?.partner_id ?? undefined,
) {
  const partnerTypes =
    doc?.type === "OUT" ? CUSTOMER_ROLE_TYPES : SUPPLIER_ROLE_TYPES;
  const picker = usePartnerPicker(
    partnerTypes,
    selectedId,
    // A saved document names its own partner whatever the role: a return of
    // a delivery is a receipt whose partner is a customer. A form still reads
    // a partner the picker cannot offer as an empty field.
    selectedId !== undefined && selectedId === doc?.partner_id,
  );
  return {
    partnerTypes,
    selectedPartnerOffered: picker.selectedOffered,
    // Named as the partner field of the form takes them.
    fieldProps: {
      partners: picker.options,
      onPartnerSearch: picker.setSearch,
      partnersLoading: picker.loading,
      partnersError: picker.error,
      retryPartners: picker.retry,
    },
  };
}
