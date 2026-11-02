import { describe, expect, it, vi } from "vitest";

import { render, screen } from "@/test/utils";
import { withLanguage } from "@/test/mocks/i18n";
import { PricelistEntriesTable } from "./PricelistEntriesTable";
import type { PartnerPricelist } from "../api/pricelist";

/**
 * The validity column printed what the API sent and spelled the open end
 * with a mathematician's infinity: `2026-09-01 → ∞`. The form on the same
 * screen showed the same date as "01.09.2026" and an empty end as "Brak
 * daty" — one date in two notations, an inch apart.
 */
function entry(overrides: Partial<PartnerPricelist> = {}): PartnerPricelist {
  return {
    id: "price-1",
    organization_id: "org-1",
    partner_id: "partner-1",
    product_template_id: "template-1",
    product_name: "Mleko",
    unit_price: "4.5",
    currency: "PLN",
    uom_id: null,
    min_quantity: null,
    valid_from: "2026-09-01",
    valid_to: null,
    notes: null,
    created_at: null,
    updated_at: null,
    ...overrides,
  };
}

function renderTable(entries: PartnerPricelist[]) {
  render(
    <PricelistEntriesTable
      entries={entries}
      isLoading={false}
      onEdit={vi.fn()}
      onDelete={vi.fn()}
      onCreate={vi.fn()}
      catalogEmpty={false}
    />,
  );
}

describe("the pricelist's validity column", () => {
  it("writes both dates the way the interface writes them", async () => {
    await withLanguage("pl", async () => {
      renderTable([entry({ valid_to: "2026-12-31" })]);

      expect(screen.getByText("01.09.2026 → 31.12.2026")).toBeInTheDocument();
      expect(screen.queryByText(/2026-09-01/)).toBeNull();
    });
  });

  it("names an open end in words, the same the form uses", async () => {
    await withLanguage("pl", async () => {
      renderTable([entry()]);

      expect(screen.getByText("01.09.2026 → Brak daty")).toBeInTheDocument();
      expect(screen.queryByText(/∞/)).toBeNull();
    });
  });
});
