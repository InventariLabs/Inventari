import type {
  DocumentLine,
  WarehouseDocument,
  WarehouseDocumentRow,
} from "@/modules/warehouse/types";

/**
 * A document line with every field the contract requires, nullable ones null.
 * Tests override only what they are about; a fixture that listed the whole
 * shape by hand drifted from the schema each time the schema grew.
 */
export function documentLine(
  overrides: Partial<DocumentLine> = {},
): DocumentLine {
  const quantity = overrides.quantity ?? "1";
  return {
    id: "line-1",
    document_id: "doc-1",
    item_id: null,
    product_template_id: null,
    name: null,
    brand: null,
    barcode: null,
    quantity,
    expected_quantity: quantity,
    // The contract requires the progress fields and the server always sends them. A fixture that
    // leaves them out is how a test exercises the screen computing the status from the quantities
    // and the document's own status, so the defaults stay "not reported" rather than a value.
    done_quantity: undefined as unknown as string,
    held_quantity: undefined as unknown as string,
    uom_id: null,
    uom: null,
    batch_number: null,
    serial_number: null,
    expiry_date: null,
    notes: null,
    line_status: "" as DocumentLine["line_status"],
    discrepancy_code: null,
    discrepancy_reason: null,
    line_number: 1,
    unit_price: null,
    tax_rate: null,
    line_value: null,
    line_tax: null,
    line_gross: null,
    currency: null,
    ...overrides,
  };
}

/** A warehouse document with every field the contract requires. */
export function warehouseDocument(
  overrides: Partial<WarehouseDocument> = {},
): WarehouseDocument {
  return {
    id: "doc-1",
    organization_id: "org-1",
    type: "IN",
    number: "PZ/1",
    status: "DRAFT",
    partner_id: null,
    partner_snapshot: {},
    corrects_document_id: null,
    source_location_id: null,
    target_location_id: null,
    scheduled_date: null,
    notes: null,
    external_reference: null,
    is_opening: false,
    lines: [],
    created_by: "user-1",
    confirmed_by: null,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    confirmed_at: null,
    completed_at: null,
    total_net: null,
    total_tax: null,
    total_gross: null,
    currency: null,
    ...overrides,
  };
}

/**
 * The documents-list row the server builds from a document
 * (`document_list_row`): the lines counted, summed per unit in the order
 * they first name it, the first two kept, and the lines that carry a
 * module's fields.
 */
export function documentRow(
  doc: WarehouseDocument = warehouseDocument(),
): WarehouseDocumentRow {
  const progress = new Map<
    string | null,
    { unit: string | null; planned: number; done: number }
  >();
  for (const line of doc.lines) {
    const unit = line.uom?.symbol?.trim() || null;
    const group = progress.get(unit) ?? { unit, planned: 0, done: 0 };
    group.planned += Number(line.expected_quantity ?? line.quantity ?? 0);
    group.done += Number(line.done_quantity ?? 0);
    progress.set(unit, group);
  }
  return {
    id: doc.id,
    type: doc.type,
    number: doc.number,
    status: doc.status,
    partner_id: doc.partner_id,
    partner_snapshot: doc.partner_snapshot,
    source_location_id: doc.source_location_id,
    target_location_id: doc.target_location_id,
    source_location_name: doc.source_location_name,
    target_location_name: doc.target_location_name,
    backorder_id: doc.backorder_id,
    corrects_document_type: doc.corrects_document_type,
    scheduled_date: doc.scheduled_date,
    notes: doc.notes,
    external_reference: doc.external_reference,
    meta_data: doc.meta_data,
    is_opening: doc.is_opening,
    created_by_name: doc.created_by_name,
    confirmed_by_name: doc.confirmed_by_name,
    completed_by_name: doc.completed_by_name,
    created_at: doc.created_at,
    completed_at: doc.completed_at,
    total_net: doc.total_net,
    total_gross: doc.total_gross,
    currency: doc.currency,
    work_stage: doc.work_stage,
    next_action: doc.next_action,
    stage_holder_name: doc.stage_holder_name,
    shipment: doc.shipment,
    line_count: doc.lines.length,
    unit_progress: [...progress.values()].map((group) => ({
      unit: group.unit,
      planned: String(group.planned),
      done: String(group.done),
    })),
    first_lines: doc.lines.slice(0, 2).map((line) => ({
      name: line.name,
      quantity: line.quantity,
      done_quantity: line.done_quantity,
      uom: line.uom
        ? { symbol: line.uom.symbol, rounding: line.uom.rounding }
        : null,
    })),
    module_lines: doc.lines
      .filter((line) => line.meta_data)
      .map((line) => ({
        id: line.id,
        batch_number: line.batch_number,
        meta_data: line.meta_data,
      })),
  };
}
