import { CUSTOMER_ROLE_TYPES, SUPPLIER_ROLE_TYPES } from "@/hooks/partnerRoles";
import type { PartnerType } from "@/types";
import type { components } from "@/types/api-generated";
import type { ProductSearchResult } from "@/modules/warehouse/api/documents";
import type { OpenPurchaseOrderLine } from "@/hooks/useOpenPurchaseOrders";
import type { DocumentMetaData, DraftLineView } from "@/lib/moduleRegistry";
import { sentMetaData } from "@/modules/warehouse/components/documentFormShared";
import type { DocumentCreate, DocumentType } from "@/modules/warehouse/types";

export type ImportedLine = components["schemas"]["DocumentImportLineResponse"];

/** Where the goods on the sheet come from, in the words a person answers with. */
export type ReceiveSource = "supplier" | "return" | "internal";

/** The reasons goods that arrived are held back; the server accepts these two. */
export type HeldCode = "DAMAGE" | "QUALITY_HOLD";

/**
 * The document each source writes. The person never picks a type: a delivery
 * and a customer's return both come in on a receipt, while goods found or
 * made on site are an internal receipt, which names no outside partner.
 */
export const RECEIVE_SOURCE_TYPE: Record<ReceiveSource, DocumentType> = {
  supplier: "IN",
  return: "IN",
  internal: "INTERNAL_IN",
};

/**
 * One row of the receive screen while it is being filled in — the form's
 * own working shape, not the wire's `DocumentLineCreate`.
 *
 * ``ordered`` is what the supplier's order still owes and is display only;
 * ``quantity`` is what arrived and is what the posting sends. A row that
 * did not come from an order has no ``ordered``, and the screen shows no
 * ordered column value for it.
 */
export interface ReceiveDraftLine {
  key: string;
  itemId: string | null;
  productTemplateId: string | null;
  name: string;
  sku: string | null;
  barcode: string | null;
  uomId: string | null;
  uomSymbol: string | null;
  ordered: string | null;
  quantity: string;
  targetLocationId: string | null;
  batchNumber: string;
  expiryDate: string;
  unitPrice: string;
  taxRate: string;
  sourcePoLineId: string | null;
  /**
   * The catalogue product an order line typed by hand arrives as, named by
   * the person receiving it. Null on every other row.
   */
  chosenProductName: string | null;
  /**
   * How much of ``quantity`` arrived damaged or waiting for a quality
   * decision, as typed; empty says all of it is ordinary stock. It is kept
   * out of available stock, and ``heldCode`` says why.
   */
  heldQuantity: string;
  heldCode: HeldCode;
  /** Other modules' fields on the line, under each module's name. */
  metaData?: DocumentMetaData;
}

/**
 * A change to one row: the fields to set, or how to work them out from the
 * row as it stands when the change lands.
 */
export type RowPatch =
  | Partial<ReceiveDraftLine>
  | ((row: ReceiveDraftLine) => Partial<ReceiveDraftLine>);

/** The line as other modules' slots see it. */
export function draftLineView(line: ReceiveDraftLine): DraftLineView {
  return {
    key: line.key,
    itemId: line.itemId,
    productTemplateId: line.productTemplateId,
    name: line.name,
    quantity: line.quantity,
    batchNumber: line.batchNumber || null,
    metaData: line.metaData ?? {},
  };
}

function emptyLine(name: string): ReceiveDraftLine {
  return {
    key: crypto.randomUUID(),
    itemId: null,
    productTemplateId: null,
    name,
    sku: null,
    barcode: null,
    uomId: null,
    uomSymbol: null,
    ordered: null,
    quantity: "1",
    targetLocationId: null,
    batchNumber: "",
    expiryDate: "",
    unitPrice: "",
    taxRate: "",
    sourcePoLineId: null,
    chosenProductName: null,
    heldQuantity: "",
    heldCode: "DAMAGE",
  };
}

/** The line a catalogue hit stands for: one unit until the reader says more. */
export function lineFromProduct(
  product: ProductSearchResult,
): ReceiveDraftLine {
  // The symbol is the wire's spelling until a screen resolves it for the
  // reader; this line is a payload, not a sentence.
  const uom = product.uom_symbol ?? null;
  return {
    ...emptyLine(product.name),
    itemId: product.item_id ?? null,
    productTemplateId: product.product_template_id ?? null,
    sku: product.sku ?? null,
    barcode: product.barcode ?? null,
    uomId: product.uom_id ?? null,
    uomSymbol: uom,
  };
}

/** A line the supplier's order already describes, pre-filled with what it owes. */
export function lineFromOrderLine(
  open: OpenPurchaseOrderLine,
): ReceiveDraftLine {
  return {
    ...emptyLine(open.name),
    productTemplateId: open.productTemplateId,
    uomId: open.uomId,
    uomSymbol: open.uomSymbol,
    ordered: open.outstanding,
    quantity: open.outstanding,
    unitPrice: open.unitPrice ?? "",
    taxRate: open.taxRate ?? "",
    sourcePoLineId: open.poLineId,
  };
}

/** A pasted or imported row, as a line of this form. */
function lineFromImport(imported: ImportedLine): ReceiveDraftLine {
  return {
    ...emptyLine(imported.name ?? ""),
    itemId: imported.item_id ?? null,
    productTemplateId: imported.product_template_id ?? null,
    barcode: imported.barcode ?? null,
    quantity: String(Number(imported.quantity) || 0),
    uomId: imported.uom_id ?? null,
    batchNumber: imported.batch_number ?? "",
    expiryDate: imported.expiry_date ?? "",
    unitPrice: imported.unit_price ?? "",
    taxRate: imported.tax_rate ?? "",
  };
}

/** The row a product already occupies, when one does. */
export function lineForProduct(
  lines: ReceiveDraftLine[],
  product: ProductSearchResult,
): ReceiveDraftLine | undefined {
  const template = product.product_template_id ?? null;
  const item = product.item_id ?? null;
  return lines.find(
    (line) =>
      (template !== null && line.productTemplateId === template) ||
      (item !== null && line.itemId === item),
  );
}

/**
 * What one scan or pick does to the sheet.
 *
 * A product already on the sheet is not added twice: the reader's eye goes
 * to the row that already exists, and the scan selects its count instead of
 * inventing a second line for the same goods. A product the sheet has never
 * seen opens a row holding one unit.
 */
export function withScannedProduct(
  lines: ReceiveDraftLine[],
  product: ProductSearchResult,
): { lines: ReceiveDraftLine[]; focusKey: string; added: boolean } {
  const existing = lineForProduct(lines, product);
  if (existing) return { lines, focusKey: existing.key, added: false };
  const added = lineFromProduct(product);
  return { lines: [...lines, added], focusKey: added.key, added: true };
}

/**
 * Pasted rows land on the sheet as quantities, not as additions.
 *
 * A spreadsheet states what arrived. A row that describes the same delivery
 * row as one already on the sheet — the same product, in the same lot, with
 * the same expiry and in the same unit — replaces that row's count, so
 * pasting "26" for a line the order expected 30 gives 26, never 56. Two rows
 * of one product in different lots are two delivery rows, though: the shelf
 * and the recall record need them apart, so the second one is not merged
 * into the first. That holds across pastes too — a later paste states
 * another delivery row, so it replaces the row it describes and leaves the
 * lots that were already on the sheet alone.
 *
 * A row the catalogue does not know cannot become a line: it is handed back
 * in ``unmatched`` so the screen names it rather than dropping it. A delivery
 * of thirty rows with three misspelt codes must not post twenty-seven lines
 * in silence.
 */
export function withImportedLines(
  lines: ReceiveDraftLine[],
  imported: ImportedLine[],
): { lines: ReceiveDraftLine[]; unmatched: ImportedLine[] } {
  const next = [...lines];
  const unmatched: ImportedLine[] = [];
  // A line this paste has already spoken for. One existing row cannot be the
  // landing place of two different delivery rows, or the second would
  // overwrite the first.
  const claimed = new Set<string>();
  for (const row of imported) {
    const line = lineFromImport(row);
    if (!line.productTemplateId && !line.itemId) {
      unmatched.push(row);
      continue;
    }
    let index = next.findIndex(
      (current) => !claimed.has(current.key) && sameDeliveryRow(current, line),
    );
    if (index < 0) {
      // The order line waiting for this product is what the first pasted row
      // of it lands on: the delivery replaces the count the order promised,
      // and the order's provenance and price stay with it. Only a row that
      // still holds just a count can take a delivery, though — once a row
      // names a lot it is a delivery row, and another lot arriving later is
      // a second row, not a correction of the first.
      index = next.findIndex(
        (current) =>
          !claimed.has(current.key) &&
          current.sourcePoLineId !== null &&
          awaitsDelivery(current) &&
          sameProduct(current, line),
      );
    }
    if (index < 0) {
      // Failing an order line, a row typed by hand is the reader's place for
      // this product; the delivery states what is really in their hands, so
      // it replaces that count rather than arriving beside it — under the
      // same rule, while the row is still only a count.
      index = next.findIndex(
        (current) =>
          !claimed.has(current.key) &&
          awaitsDelivery(current) &&
          sameProduct(current, line),
      );
    }
    if (index >= 0) {
      claimed.add(next[index].key);
      next[index] = mergeImportedLine(next[index], line);
      continue;
    }
    // A further delivery row of a product the order is waiting for still
    // arrived against that order line: the receipt must credit it, or the
    // order reads short after a delivery that came in full.
    const order = next.find(
      (current) =>
        current.sourcePoLineId !== null && sameProduct(current, line),
    );
    const added = order
      ? {
          ...line,
          sourcePoLineId: order.sourcePoLineId,
          uomId: line.uomId ?? order.uomId,
          uomSymbol: line.uomSymbol ?? order.uomSymbol,
          unitPrice: line.unitPrice || order.unitPrice,
          taxRate: line.taxRate || order.taxRate,
        }
      : line;
    claimed.add(added.key);
    next.push(added);
  }
  return { lines: next, unmatched };
}

/** Whether two rows name the same product. */
function sameProduct(a: ReceiveDraftLine, b: ReceiveDraftLine): boolean {
  return (
    (a.productTemplateId !== null &&
      a.productTemplateId === b.productTemplateId) ||
    (a.itemId !== null && a.itemId === b.itemId)
  );
}

/**
 * Whether a row still holds nothing but a count: no lot and no expiry.
 *
 * That is a row waiting for the goods — an order line not yet delivered, or
 * a row typed by hand — so a delivery may state its count and identity. A
 * row that already names a lot is a delivery row: another lot arriving is a
 * row of its own, and this one must keep its count.
 */
function awaitsDelivery(line: ReceiveDraftLine): boolean {
  return line.batchNumber === "" && line.expiryDate === "";
}

/**
 * Whether two rows describe one delivery row: the same product, in the same
 * lot, expiring the same day, counted in a unit they can be added in.
 *
 * This is the identity a delivery note's row states. A row that states no
 * unit can be counted in the line's; two stated units that differ cannot be
 * one quantity.
 */
function sameDeliveryRow(
  current: ReceiveDraftLine,
  incoming: ReceiveDraftLine,
): boolean {
  if (!sameProduct(current, incoming)) return false;
  if (
    current.batchNumber !== incoming.batchNumber ||
    current.expiryDate !== incoming.expiryDate
  ) {
    return false;
  }
  return (
    current.uomId === null ||
    incoming.uomId === null ||
    current.uomId === incoming.uomId
  );
}

/** A pasted delivery row's counts laid over the row it lands on. */
function mergeImportedLine(
  current: ReceiveDraftLine,
  incoming: ReceiveDraftLine,
): ReceiveDraftLine {
  return {
    ...current,
    quantity: incoming.quantity,
    batchNumber: incoming.batchNumber || current.batchNumber,
    expiryDate: incoming.expiryDate || current.expiryDate,
    unitPrice: incoming.unitPrice || current.unitPrice,
    taxRate: incoming.taxRate || current.taxRate,
    uomId: current.uomId ?? incoming.uomId,
  };
}

/**
 * The supplier's order, laid over the sheet the reader already has.
 *
 * A row typed before the order arrived keeps its count — the reader has
 * already said what is in their hands — and gains the order's expected
 * count, price and source line. It takes the first order line of its
 * product; a second order line of the same product is a second count at a
 * second price and keeps a row of its own. Rows of the previous order are
 * gone by the time this runs; rows the order does not mention stay as they
 * are.
 */
export function withOrderLines(
  lines: ReceiveDraftLine[],
  openLines: OpenPurchaseOrderLine[],
): ReceiveDraftLine[] {
  const next = [...lines];
  for (const open of openLines) {
    // The same order line already on the sheet keeps its row: laying an
    // order over a sheet that already has it must not add it twice.
    let index = next.findIndex((line) => line.sourcePoLineId === open.poLineId);
    if (index < 0) {
      index =
        open.productTemplateId === null
          ? -1
          : next.findIndex(
              (line) =>
                line.sourcePoLineId === null &&
                line.productTemplateId === open.productTemplateId,
            );
    }
    if (index < 0) {
      next.push(lineFromOrderLine(open));
      continue;
    }
    const line = next[index];
    next[index] = {
      ...line,
      ordered: open.outstanding,
      sourcePoLineId: open.poLineId,
      uomId: line.uomId ?? open.uomId,
      uomSymbol: line.uomSymbol ?? open.uomSymbol,
      unitPrice: line.unitPrice || open.unitPrice || "",
      taxRate: line.taxRate || open.taxRate || "",
    };
  }
  return next;
}

/** Whether the row says part of what arrived is held back. */
export function isHeld(line: ReceiveDraftLine): boolean {
  return Number(line.heldQuantity) > 0;
}

/** The document the screen posts: the receipt itself, with every row's count. */
export function toDocumentCreate(args: {
  /** What the source chose: a receipt, or an internal receipt. */
  docType: DocumentType;
  partnerId: string | null;
  targetLocationId: string;
  externalReference: string;
  lines: ReceiveDraftLine[];
  /** Prices came from an order or the accounting toggle: send them. */
  includePrices: boolean;
  /** Other modules' fields on the document. */
  metaData?: DocumentMetaData;
}): DocumentCreate {
  return {
    type: args.docType,
    partner_id: args.partnerId || undefined,
    target_location_id: args.targetLocationId,
    external_reference: args.externalReference.trim() || undefined,
    meta_data: sentMetaData(args.metaData),
    lines: args.lines.map((line) => ({
      item_id: line.itemId || undefined,
      product_template_id: line.productTemplateId || undefined,
      name: line.name || undefined,
      sku: line.sku || undefined,
      barcode: line.barcode || undefined,
      expected_quantity: line.quantity,
      uom_id: line.uomId || undefined,
      batch_number: line.batchNumber || undefined,
      expiry_date: line.expiryDate || undefined,
      target_location_id: line.targetLocationId || undefined,
      source_po_line_id: line.sourcePoLineId || undefined,
      // A row nobody ordered holds the count the reader typed, which is no
      // expectation to exceed when the goods are counted again on a phone.
      expected_is_count: line.sourcePoLineId ? undefined : true,
      ...(isHeld(line)
        ? { held_quantity: line.heldQuantity, discrepancy_code: line.heldCode }
        : {}),
      // A line loaded from the order carries the price the order agreed,
      // even while the screen keeps prices out of the reader's way; a
      // hand-entered line only has a price when accounting asked for one.
      unit_price:
        args.includePrices || line.sourcePoLineId
          ? line.unitPrice || undefined
          : undefined,
      tax_rate:
        args.includePrices || line.sourcePoLineId
          ? line.taxRate || undefined
          : undefined,
      meta_data: sentMetaData(line.metaData),
    })),
  };
}

/** Counts for the footer: lines, and a quantity only when one unit covers all. */
export function draftTotals(lines: ReceiveDraftLine[]): {
  count: number;
  quantity: string | null;
  unit: string | null;
} {
  if (lines.length === 0) return { count: 0, quantity: null, unit: null };
  const unit = lines[0].uomSymbol;
  const sameUnit = lines.every((line) => line.uomSymbol === unit);
  if (!sameUnit || !unit) {
    return { count: lines.length, quantity: null, unit: null };
  }
  const total = lines.reduce(
    (sum, line) => sum + (Number(line.quantity) || 0),
    0,
  );
  return {
    count: lines.length,
    quantity: String(Math.round(total * 1e6) / 1e6),
    unit,
  };
}

/** What the delivery still owes the supplier's order, counted per order line. */
export interface ShortDelivery {
  /** Order lines the delivery does not cover in full. */
  count: number;
  /** The row of each short order line that wears the mark. */
  rowKeys: Set<string>;
}

/**
 * Order lines the delivery does not cover in full.
 *
 * The question goes to the order, not to the sheet. A line the reader removed
 * because it did not arrive is still owed, and an order measured only over
 * the rows left on the sheet would call that delivery complete — the footer
 * would promise "the whole order arrived" over a purchase order that still
 * waits for goods. Every outstanding order line is therefore accounted for,
 * including the ones this delivery does not mention at all.
 *
 * A delivery that came in several lots shares one order line between its
 * rows: what the order waits for is the sum over the rows that name it, not
 * each row measured on its own. The row that carries the order's count is
 * the one marked, so the mark is per order line, not per delivery row; a
 * line with no row left has nothing to mark, and the count carries it.
 */
export function shortDelivery(
  lines: ReceiveDraftLine[],
  orderLines: OpenPurchaseOrderLine[],
): ShortDelivery {
  const arrived = new Map<string, number>();
  for (const line of lines) {
    if (line.sourcePoLineId === null) continue;
    arrived.set(
      line.sourcePoLineId,
      (arrived.get(line.sourcePoLineId) ?? 0) + (Number(line.quantity) || 0),
    );
  }

  const short = orderLines.filter(
    (open) => (arrived.get(open.poLineId) ?? 0) < Number(open.outstanding),
  );
  const rowKeys = new Set<string>();
  for (const open of short) {
    const rows = lines.filter((line) => line.sourcePoLineId === open.poLineId);
    const carrying = rows.find((line) => line.ordered !== null) ?? rows[0];
    if (carrying) rowKeys.add(carrying.key);
  }
  return { count: short.length, rowKeys };
}

/** What the sheet can be refused for, in the vocabulary the catalogues use. */
export type DraftProblem =
  "noWarehouse" | "noLines" | "noProduct" | "noQuantity" | "heldAboveReceived";

/** Why the sheet cannot post, and the row whose own value is the cause. */
export interface DraftRefusal {
  problem: DraftProblem;
  lineKey?: string;
}

/** The first thing that stops the sheet from being posted, if anything. */
export function draftProblem(
  lines: ReceiveDraftLine[],
  targetLocationId: string,
): DraftRefusal | null {
  if (!targetLocationId) return { problem: "noWarehouse" };
  if (lines.length === 0) return { problem: "noLines" };
  for (const line of lines) {
    if (!line.productTemplateId && !line.itemId) {
      return { problem: "noProduct" };
    }
    const quantity = Number(line.quantity);
    if (!Number.isFinite(quantity) || quantity <= 0) {
      return { problem: "noQuantity", lineKey: line.key };
    }
    if (Number(line.heldQuantity) > quantity) {
      return { problem: "heldAboveReceived", lineKey: line.key };
    }
  }
  return null;
}

/**
 * The rows a `RECEIPT_EXPIRY_REQUIRED` refusal names. The server numbers the
 * lines of a receipt it has just created in the order the sheet sent them, so
 * a row's place on the sheet is its line number less one.
 */
export function undatedRows(
  named: Record<string, unknown>[] | null,
  lines: ReceiveDraftLine[],
): ReceiveDraftLine[] {
  const rows: ReceiveDraftLine[] = [];
  for (const row of named ?? []) {
    const line = lines[Number(row.line_number) - 1];
    if (line && !rows.includes(line)) rows.push(line);
  }
  return rows;
}

/** Who the partner field offers: a customer's goods come back from a
 *  customer. An internal receipt names nobody, and its field is hidden. */
export function partnerTypesFor(source: ReceiveSource): readonly PartnerType[] {
  return source === "return" ? CUSTOMER_ROLE_TYPES : SUPPLIER_ROLE_TYPES;
}
