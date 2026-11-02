import type { PartnerType } from "@/types";

/**
 * Canonical partner role sets — the frontend mirror of the sets
 * defined once in Core (`app/schemas/partner.py`).
 *
 * Lives beside the Core `usePartners` shim: any module may read the role
 * sets from here without reaching into the partners module — a document
 * dropdown and a purchase-order dropdown name the same sets the backend
 * enforces, and a cross-module edge is a fact about the domain, not a
 * favour one module does another.
 *
 * A manufacturer also delivers goods, and BOTH covers "we buy from and sell
 * to the same entity", so the supplier set answers "who can be a supplier?"
 * the same way everywhere: document dropdowns, the purchase-order dropdown,
 * the pricelist and backend validation.
 */
export const SUPPLIER_ROLE_TYPES: readonly PartnerType[] = [
  "SUPPLIER",
  "BOTH",
  "MANUFACTURER",
];

export const CUSTOMER_ROLE_TYPES: readonly PartnerType[] = ["CUSTOMER", "BOTH"];

/** Every partner type, in the order the form and the import offer them. */
export const PARTNER_TYPES: readonly PartnerType[] = [
  "SUPPLIER",
  "CUSTOMER",
  "BOTH",
  "SERVICE_PROVIDER",
  "MANUFACTURER",
  "EMPLOYEE",
];
