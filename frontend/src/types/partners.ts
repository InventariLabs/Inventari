// Partner types.
import type { components } from "./api-generated";

export type PartnerType =
  | "SUPPLIER"
  | "CUSTOMER"
  | "BOTH"
  | "SERVICE_PROVIDER"
  | "MANUFACTURER"
  | "EMPLOYEE";

export type PartnerAddress = components["schemas"]["PartnerAddress"];

/**
 * A partner as the list endpoint answers (`PartnerListItem` on the wire —
 * the schema carries the collaboration counters a detail response does
 * not). The wire type `Partner` does not exist; the hand-written body was
 * a mirror of `PartnerListItem` under the shorter name.
 */
export type Partner = components["schemas"]["PartnerListItem"];

export type PartnerCreate = components["schemas"]["PartnerCreate"];

export type PartnerUpdate = components["schemas"]["PartnerUpdate"];

export type PartnerListResponse =
  components["schemas"]["PaginatedResponse_PartnerListItem_"];

/** What one partner import did; `errors` names the row and the reason. */
export type PartnerImportResponse =
  components["schemas"]["PartnerImportResponse"];
