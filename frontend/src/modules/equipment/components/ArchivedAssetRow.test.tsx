import { describe, expect, it, vi } from "vitest";
import { screen } from "@testing-library/react";
import { renderWithProviders } from "@/test/utils";
import type { ArchivedItem } from "@/types";
import { ArchivedAssetRow } from "./ArchivedAssetRow";

const asset: ArchivedItem = {
  id: "a-1",
  name: "Desk Lamp",
  quantity: "1.000",
  purchase_price: "120.00",
  currency: "PLN",
  is_deleted: true,
  deleted_at: "2026-07-01T00:00:00Z",
  deleted_by: null,
  deletion_reason: "ARCHIVED",
  category: { id: "c-1", name: "Office equipment", code: null, icon: null },
  location_id: "loc-1",
  category_id: "c-1",
};

function renderRow(overrides: Partial<ArchivedItem> = {}) {
  return renderWithProviders(
    <ArchivedAssetRow
      item={{ ...asset, ...overrides }}
      isSelected={false}
      isRestorePending={false}
      isPurgePending={false}
      onToggleSelect={vi.fn()}
      onRestore={vi.fn()}
      onPurge={vi.fn()}
    />,
  );
}

describe("ArchivedAssetRow", () => {
  it("speaks the reader's word for the reason, not the database's", () => {
    // The badge printed the raw dictionary value — "EXPIRED",
    // "ARCHIVED" — where the inventory archive, reading the same dictionary,
    // says "Expired". The row now draws from the same catalogue of words.
    renderRow();
    expect(screen.getByText("Archived")).toBeInTheDocument();
    expect(screen.queryByText("ARCHIVED")).not.toBeInTheDocument();
  });

  it("translates the reasons a person chose themselves", () => {
    renderRow({ deletion_reason: "expired" }); // lowercase, as the DB stores it
    expect(screen.getByText("Expired")).toBeInTheDocument();
    expect(screen.queryByText(/deletionReasons/i)).not.toBeInTheDocument();
  });

  it("stays silent when no reason was given", () => {
    renderRow({ deletion_reason: null });
    expect(screen.queryByText("Archived")).not.toBeInTheDocument();
  });
});
