import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { DocumentMetadataGrid } from "./DocumentMetadataGrid";
import type { WarehouseDocument } from "../types";

const modules = vi.hoisted(() => ({ enabled: [] as string[] }));
vi.mock("@/contexts/ModulesContext", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/contexts/ModulesContext")>()),
  useEnabledModulesOptional: () => modules.enabled,
}));

/**
 * What a document points at, read months later from its own page: the
 * order it was received against, and the reference it carries.
 */

const t = (key: string) =>
  ({
    "warehouse:fields.sourceOrder": "Purchase order",
    "warehouse:fields.externalReference": "Reference / related document",
    "warehouse:references.stockTake": "Stock take",
    "warehouse:references.recipeProduction": "Recipe production",
  })[key] ?? key;

const ID = "3f2b8c1e-5d4a-4b6f-9e7d-1a2b3c4d5e6f";

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
  beforeEach(() => {
    modules.enabled = ["stock_takes", "recipes"];
  });

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

  it("names a stock take's reference in words and links to its report", () => {
    renderGrid(
      receipt({ type: "INTERNAL_IN", external_reference: `stock_take:${ID}` }),
    );

    expect(screen.getByRole("link", { name: /Stock take/ })).toHaveAttribute(
      "href",
      `/inventory/stock-takes/${ID}/report`,
    );
    expect(screen.queryByText(new RegExp(ID))).toBeNull();
  });

  it("names a recipe's cooking in words and links to the recipe", () => {
    renderGrid(
      receipt({ type: "INTERNAL_OUT", external_reference: `recipe:${ID}` }),
    );

    expect(
      screen.getByRole("link", { name: /Recipe production/ }),
    ).toHaveAttribute("href", `/recipes/${ID}`);
  });

  it("names a picking session in words, with no page to open", () => {
    renderGrid(
      receipt({ type: "INTERNAL_OUT", external_reference: `picking:${ID}` }),
    );

    expect(screen.getByText("Recipe production")).toBeVisible();
    expect(screen.queryByRole("link")).toBeNull();
    expect(screen.queryByText(new RegExp(ID))).toBeNull();
  });

  it("offers no page while the module that serves it is off", () => {
    modules.enabled = [];
    renderGrid(
      receipt({ type: "INTERNAL_IN", external_reference: `stock_take:${ID}` }),
    );

    expect(screen.getByText("Stock take")).toBeVisible();
    expect(screen.queryByRole("link")).toBeNull();
  });

  it("keeps a typed reference that only looks like one, as typed", () => {
    renderGrid(receipt({ external_reference: "stock_take:week 4" }));

    expect(screen.getByText("stock_take:week 4")).toBeVisible();
  });
});
