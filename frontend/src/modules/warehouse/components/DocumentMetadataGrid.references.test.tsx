import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { DocumentMetadataGrid } from "./DocumentMetadataGrid";
import type { WarehouseDocument } from "../types";

/**
 * What a document points at, read months later from its own page: the
 * order it was received against, and the reference it carries.
 */

const t = (key: string) =>
  ({
    "warehouse:fields.sourceOrder": "Purchase order",
    "warehouse:fields.externalReference": "Reference / related document",
  })[key] ?? key;

function receipt(
  overrides: Partial<WarehouseDocument> = {},
): WarehouseDocument {
  return {
    id: "doc-1",
    organization_id: "org-1",
    type: "IN",
    number: "PZ/2026/11/0001",
    status: "COMPLETED",
    partner_id: null,
    source_location_id: null,
    target_location_id: null,
    scheduled_date: null,
    notes: null,
    external_reference: null,
    source_orders: [],
    lines: [],
    created_by: "u-1",
    created_at: "2026-11-19T09:00:00Z",
    updated_at: "2026-11-19T09:00:00Z",
    confirmed_at: null,
    completed_at: null,
    ...overrides,
  } as unknown as WarehouseDocument;
}

function renderGrid(doc: WarehouseDocument) {
  render(
    <MemoryRouter>
      <DocumentMetadataGrid
        doc={doc}
        isDraft={false}
        partners={[]}
        storages={[]}
        notesEditValue={null}
        onNotesChange={() => {}}
        onNotesBlur={() => {}}
        onPartnerChange={() => {}}
        formatDate={() => "2026-11-19"}
        formatDateTime={() => "2026-11-19 09:00"}
        t={t}
      />
    </MemoryRouter>,
  );
}

describe("DocumentMetadataGrid references", () => {
  it("names the purchase order a receipt came from and links to it", () => {
    renderGrid(
      receipt({
        external_reference: "WZ-778/2026",
        source_orders: [{ id: "po-1", number: "PO/2026/11/0001" }],
      }),
    );

    expect(screen.getByText("Purchase order")).toBeVisible();
    expect(
      screen.getByRole("link", { name: /PO\/2026\/11\/0001/ }),
    ).toHaveAttribute("href", "/purchase-orders/po-1");
    expect(screen.getByText("WZ-778/2026")).toBeVisible();
  });

  it("does not repeat an order number kept as the reference", () => {
    renderGrid(
      receipt({
        external_reference: "PO/2026/11/0001",
        source_orders: [{ id: "po-1", number: "PO/2026/11/0001" }],
      }),
    );

    expect(screen.getAllByText("PO/2026/11/0001")).toHaveLength(1);
    expect(screen.queryByText("Reference / related document")).toBeNull();
  });

  it("names no order on a receipt without one", () => {
    renderGrid(receipt());

    expect(screen.queryByText("Purchase order")).toBeNull();
  });
});
