import type { DocumentMetaData, DraftLineView } from "@/lib/moduleRegistry";

/** A line of the receipt form while it is being typed — not the wire's `ReceiptLineSchema`. */
export interface ReceiptDraftLine {
  _key: string;
  item_id?: string;
  product_template_id?: string;
  name: string;
  brand?: string;
  barcode?: string;
  sku?: string;
  image_url?: string;
  quantity: number;
  uom_id?: string | null;
  batch_number: string;
  serial_number?: string;
  expiry_date: string;
  notes: string;
  unit_price?: string;
  tax_rate?: string;
  /** Other modules' fields on the line, sent back with it on every save. */
  meta_data?: DocumentMetaData;
}

/**
 * *meta* with one module's values put under its name: replaced, or removed
 * when there are none. Every other module's key is kept as it was.
 */
export function withModuleValues(
  meta: DocumentMetaData | null | undefined,
  module: string,
  values: Record<string, unknown> | null,
): DocumentMetaData {
  const { [module]: _replaced, ...others } = meta ?? {};
  return values && Object.keys(values).length > 0
    ? { ...others, [module]: values }
    : others;
}

/** What a new document sends: nothing at all when no module wrote anything. */
export function sentMetaData(
  meta: DocumentMetaData | null | undefined,
): DocumentMetaData | undefined {
  return meta && Object.keys(meta).length > 0 ? meta : undefined;
}

/** The line as other modules' slots see it. */
export function receiptLineView(line: ReceiptDraftLine): DraftLineView {
  return {
    key: line._key,
    itemId: line.item_id ?? null,
    productTemplateId: line.product_template_id ?? null,
    name: line.name,
    quantity: String(line.quantity),
    batchNumber: line.batch_number || null,
    metaData: line.meta_data ?? {},
  };
}

export interface QuickAddLineDraft {
  item_id?: string;
  /** The catalogue product a scanned code already names. */
  product_template_id?: string | null;
  /**
   * The line whose typed name opened this panel: the product made here takes
   * that line's place instead of adding another.
   */
  replaces?: string;
  name: string;
  brand: string;
  barcode: string;
  sku: string;
  image_url?: string;
  /**
   * Null while the quantity field is empty — the field reports null rather
   * than guessing a number, and submit refuses a line without one.
   */
  quantity: number | null;
  uom_id?: string | null;
  batch_number: string;
  serial_number?: string;
  expiry_date: string;
  notes: string;
}

export function createEmptyQuickAddLineDraft(): QuickAddLineDraft {
  return {
    item_id: undefined,
    name: "",
    brand: "",
    barcode: "",
    sku: "",
    image_url: undefined,
    quantity: 1,
    uom_id: null,
    batch_number: "",
    serial_number: "",
    expiry_date: "",
    notes: "",
  };
}

/** What the line editor shows under a row: the name field's and the quantity's. */
export type LineFieldErrors = Record<
  string,
  { name?: string; quantity?: string }
>;

/**
 * The form's errors regrouped per line, keyed by the line's stable `_key`.
 * "Needs a product" and "needs a stock record" both surface on the name
 * field, the record taking precedence. Client errors are i18n keys
 * (`errors.*`) and are translated; a 422 carries the server's own sentence,
 * which passes through as it is.
 */
export function lineFieldErrors(
  errors: Record<string, string>,
  lines: ReceiptDraftLine[],
  t: (key: string) => string,
): LineFieldErrors {
  const render = (msg: string) => (msg.startsWith("errors.") ? t(msg) : msg);
  const byLine: LineFieldErrors = {};
  for (const line of lines) {
    const itemIdMsg = errors[`line.${line._key}.item_id`];
    const nameMsg = errors[`line.${line._key}.name`];
    const quantityMsg = errors[`line.${line._key}.quantity`];
    if (!itemIdMsg && !nameMsg && !quantityMsg) continue;
    const nameError = itemIdMsg ?? nameMsg;
    byLine[line._key] = {
      ...(nameError ? { name: render(nameError) } : {}),
      ...(quantityMsg ? { quantity: render(quantityMsg) } : {}),
    };
  }
  return byLine;
}
