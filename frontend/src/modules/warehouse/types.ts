import type { components } from "@/types/api-generated";
import type { WithServerDefaults } from "@/types/request";
// Warehouse document types.

/**
 * Every document type the module knows, in the order screens present them.
 *
 * One list, because there were three: the tabs on the list, the chips in the
 * profile and the filter in the register each carried their own — and the
 * register's was one type short, so scrap documents could be written and then
 * not found in the ledger that is supposed to account for them.
 *
 * The name a type goes by is `warehouse:types.<CODE>` (long) or
 * `warehouse:typesShort.<CODE>` (compact). The code itself is an identifier,
 * never a label: nobody asked for a workflow on "OUT".
 *
 * Which key goes where is a rule, not a preference:
 *
 * - `typesShort` is for dense, repeated rows — the register's filter chips and
 *   the type column. Polish carries the paperwork codes there (PZ, WZ, MM,
 *   PW, RW, KOR, ZL); the other four languages carry the bare name.
 * - `types` is for every context that has room to say what the type IS: the
 *   document list's type tabs, the "New document" menu and the
 *   approval-thresholds screen, where an administrator decides which types
 *   need a workflow. A tab that reads "PZ" alone names the code, not the kind
 *   of work. In Polish `types` appends the code in brackets — "Przyjęcie
 *   (PZ)" — which keeps the abbreviation for the experienced reader without
 *   making it the whole label.
 *
 * The PL Magazyn profile preset numbers documents with the same codes, so the
 * bracket in the label and the prefix on the number agree.
 */
export const DOCUMENT_TYPES = [
  "IN",
  "OUT",
  "INT",
  "INTERNAL_IN",
  "INTERNAL_OUT",
  "CORRECTION",
  "SCRAP",
] as const satisfies readonly DocumentType[];

export type DocumentType = components["schemas"]["DocumentType"];
export type DocumentStatus = components["schemas"]["DocumentStatus"];
export type DocumentLineStatus = components["schemas"]["DocumentLineStatus"];
export type DocumentDiscrepancyCode =
  components["schemas"]["DocumentDiscrepancyCode"];

/**
 * Types that hold a reservation on the shelf when confirmed, mirroring the
 * backend's `needs_quant_reservation`. Cancelling one of these gives the
 * reserved stock back; cancelling a receipt gives nothing back, and telling
 * the reader otherwise promises a return that never happens.
 */
const RESERVING_DOCUMENT_TYPES: ReadonlySet<string> = new Set([
  "OUT",
  "INTERNAL_OUT",
  "INT",
  "SCRAP",
  "RW",
]);

/** Cancelling a document of this type and status releases a reservation. */
export function cancelReleasesStock(type: string, status: string): boolean {
  return (
    RESERVING_DOCUMENT_TYPES.has(type) &&
    (status === "CONFIRMED" || status === "PENDING_APPROVAL")
  );
}

/**
 * Types one press of "Undo" reverses, mirroring the backend's
 * `UNDOABLE_TYPES` (warehouse/document_correction_service.py): a receipt, an
 * issue, a move or a write-off — the four the one-screen actions post. A
 * correction restates a difference of its own and a stock take is a count —
 * a mistake in either is another document, not the absence of the first.
 */
export const UNDOABLE_DOCUMENT_TYPES: ReadonlySet<string> = new Set([
  "IN",
  "INTERNAL_IN",
  "OUT",
  "INTERNAL_OUT",
  "INT",
  "SCRAP",
]);

/** The verb "Undo" wears for a document type, in the warehouse's own words. */
export function undoLabelKey(type: string): string {
  if (type === "OUT" || type === "INTERNAL_OUT")
    return "warehouse:actions.undoIssue";
  if (type === "INT") return "warehouse:actions.undoMove";
  if (type === "SCRAP") return "warehouse:actions.undoScrap";
  return "warehouse:actions.undoReceive";
}

/**
 * Types whose correction moves stock the other way round, mirroring the
 * backend's `correction_sign` (warehouse/document_types.py): a correction's
 * lines are signed deltas on the document it corrects, and the executor
 * applies them as written for a receipt-like original, inverted for a
 * dispatch-like one. A scrap is a write-off, so less scrapped puts goods
 * back on the shelf — and a screen reading the delta's own sign alone names
 * those goods "Removed".
 */
const DISPATCH_LIKE_ORIGINALS: ReadonlySet<string> = new Set([
  "OUT",
  "WZ",
  "INTERNAL_OUT",
  "RW",
  "SCRAP",
]);

/** Which way a correction moves stock, by the type of the document it
 * corrects. `1` — the delta as written — is the answer for every
 * receipt-like original, for a document that corrects nothing (the field
 * is null) and for a payload from before the field existed. */
export function correctionStockSign(
  originalType: string | null | undefined,
): 1 | -1 {
  return originalType && DISPATCH_LIKE_ORIGINALS.has(originalType) ? -1 : 1;
}

const PICKED_BEFORE_POSTING: ReadonlySet<string> = new Set([
  "OUT",
  "INT",
  "INTERNAL_OUT",
]);

/** The types whose goods can be picked from the shelves before they leave. */
export function isPickedBeforePosting(type: string): boolean {
  return PICKED_BEFORE_POSTING.has(type);
}

/**
 * Whether a draft may be planned rather than posted now: a future date is a
 * plan by itself, and an issue needs one today too, since a picking session
 * starts on a planned document. Today's issue used to reach picking only after
 * the office dated it tomorrow.
 */
export function mayBePlanned(
  type: string,
  scheduledDate: string | null | undefined,
  today: string,
): boolean {
  return (!!scheduledDate && scheduledDate > today) || type === "OUT";
}

export type TaxHandling = "NONE" | "SIMPLE_RATE" | "PER_LINE_RATE";

/**
 * The types whose lines carry price and VAT: goods coming in or going out,
 * from a partner or between the organization's own shelves. A transfer
 * moves the same goods to another shelf without changing what they are
 * worth, a correction records a difference and a scrap writes goods off —
 * none of the three asks for a price, so no screen offers one (the backend
 * asks the same question through `carries_value`, where it governs the
 * profile's "require a unit price" rule and the printout).
 */
const VALUE_CARRYING_TYPES: ReadonlySet<string> = new Set([
  "IN",
  "OUT",
  "INTERNAL_IN",
  "INTERNAL_OUT",
  "PZ",
  "WZ",
  "PW",
  "RW",
]);

/**
 * Whether this screen may show price, VAT, totals or a value warning for
 * this document. Two halves, both required: the organization has to track
 * the value of stock at all, and the document has to be one whose lines
 * carry a price.
 *
 * What a document *stores* is a separate question — values already written
 * stay where they are, and the register lists them as before. This decides
 * only what a screen puts in front of a reader.
 */
export function showsDocumentValue(
  type: string,
  tracksValue: boolean,
): boolean {
  return tracksValue && VALUE_CARRYING_TYPES.has(type);
}

export type DocumentSummary = components["schemas"]["DocumentSummary"];

export type CorrectionCreate = components["schemas"]["CorrectionCreate"];

export type ReturnCreate = components["schemas"]["ReturnCreate"];

export type DocumentProfile = components["schemas"]["DocumentProfileSchema"];

/** One registered pick order, as the warehouse settings offer it. */
export type PickOrderStrategy =
  components["schemas"]["PickOrderStrategySchema"];

export interface DocumentProfileUpdate {
  name?: string;
  value_tracking_enabled?: boolean;
  tax_handling?: TaxHandling;
  default_tax_rate?: string | number | null;
  require_partner_tax_id?: boolean | null;
  require_unit_price?: boolean;
  confirm_shelf_by_scan?: boolean;
  /** The shelf goods coded Damage or Quality hold are received onto; null names none. */
  quarantine_location_id?: string | null;
  numbering_format?: string;
  number_padding?: number;
  type_labels?: Record<string, string> | null;
  default_unit?: string;
  visible_line_fields?: string[];
  print_template?: string;
  /** The organization's own template rendered on the printout. */
  default_template_id?: string | null;
  default_currency?: string | null;
  approval_threshold?: string | number | null;
  approval_required_for_types?: string[];
  /** The registered pick order the warehouse is walked by; null walks the default. */
  pick_order_strategy?: string | null;
  /** Carrier name → its tracking page with `{tracking_number}`; `{}` clears. */
  tracking_url_templates?: Record<string, string> | null;
}

export type DocumentLine = components["schemas"]["DocumentLineSchema"];

/** What a caller sends to complete a document; the unit confirmation and the as-planned flag it does not need are the server's defaults. */
export type DocumentCompletePayload = WithServerDefaults<
  components["schemas"]["DocumentComplete"],
  "unit_confirmed_over_template" | "complete_as_planned"
>;

export type WarehouseDocument = components["schemas"]["DocumentSchema"];

/** The reserve move an alert proposes, its lines already prepared. */
export type ReplenishmentProposal =
  components["schemas"]["ReplenishmentProposalDTO"];

/** The transfer posting a proposal made: its number, and whether it waits. */
export type ReplenishmentMove = components["schemas"]["DocumentStateDTO"];

/** Lots and expiry dates a one-step posting carries; it has no quantities. */
export type DocumentTrackingPayload = components["schemas"]["DocumentTracking"];

/** To do's two work lists and the decisions waiting on a person. */
export type DocumentsTodoResponse =
  components["schemas"]["DocumentsTodoResponse"];

/** One task on To do, whatever it was derived from. */
export type WorkItem = components["schemas"]["WorkItemSchema"];
export type WorkItemMeasures = components["schemas"]["WorkItemMeasures"];

/** What waits on a decision; To do shows its quarantine holds. */
export type TodoDecisions = DocumentsTodoResponse["decisions"];
export type QuarantineHold = components["schemas"]["QuarantineHoldSchema"];

export type DocumentLineCreate = components["schemas"]["DocumentLineCreate"];

export type DocumentCreate = components["schemas"]["DocumentCreate"];

// An alias, not a copy: the update payload is a partial PATCH whose keys the
// server reads for presence (backend AGENTS.md §2b), and the wire already
// types every field `| null` — a null is how the screen says "clear this".
export type DocumentUpdate = components["schemas"]["DocumentUpdate"];

export type DocumentListResponse =
  components["schemas"]["DocumentListResponse"];

/**
 * A document as the documents list carries it: no lines, their count and
 * sums instead (`line_count`, `unit_progress`, `first_lines`), and the lines
 * a module's column reads (`module_lines`). The document's own screen
 * fetches the whole document.
 */
export type WarehouseDocumentRow =
  components["schemas"]["DocumentListRowSchema"];

export type DocumentRowListResponse =
  components["schemas"]["DocumentRowListResponse"];

// ─── Register types ───────────────────────────────────────────────────────────

export type RegisterDocumentRow = components["schemas"]["RegisterDocumentRow"];

export type RegisterCurrencyTotal =
  components["schemas"]["RegisterCurrencyTotal"];

export type RegisterGroup = components["schemas"]["RegisterGroup"];

/** One page of one group's documents. */
export type RegisterRowsResponse =
  components["schemas"]["PaginatedResponse_RegisterDocumentRow_"];

export type RegisterResponse = components["schemas"]["RegisterResponse"];

export interface RegisterParams {
  date_from: string;
  date_to: string;
  type?: string;
  status?: string;
  partner_id?: string;
  location_id?: string;
  group_by?: "type" | "partner" | "location" | "month";
  output_format?: "csv";
}

/** Query for one group's row page. */
export interface RegisterRowsParams {
  date_from: string;
  date_to: string;
  /** The group to page through; "" is the no-partner/no-location bucket. */
  group_key: string;
  group_by?: "type" | "partner" | "location" | "month";
  type?: string;
  status?: string;
  partner_id?: string;
  location_id?: string;
  offset?: number;
  limit?: number;
}

export type DocumentApprovalStatus =
  "PENDING" | "APPROVED" | "REJECTED" | "IN_PROGRESS";

export interface DocumentApproval {
  id: string;
  status: DocumentApprovalStatus;
  requested_by: string;
  approver_user_id: string | null;
  notes: string | null;
  created_at: string;
  decided_at: string | null;
}

/**
 * Whether confirming a document would send it to the approval queue.
 *
 * The rule behind it is the backend's own — the profile's listed types and
 * threshold, and, when the profile names neither, an active approval
 * workflow for documents — so the sentence the confirm dialog shows and the
 * thing confirmation then does cannot disagree. The alias is the generated
 * schema, not a copy of it.
 */
export type DocumentApprovalRequirement =
  components["schemas"]["DocumentApprovalRequirement"];

export type InventoryPeriod = components["schemas"]["InventoryPeriodSchema"];

/** What an opening-stock sheet became: one draft receipt, or nothing. */
export type OpeningStockImportResponse =
  components["schemas"]["OpeningStockImportResponse"];
