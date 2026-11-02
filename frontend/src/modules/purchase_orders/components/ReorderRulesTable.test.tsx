import { describe, expect, it, vi } from "vitest";
import { render, screen, within } from "@/test/utils";
import { withLanguage } from "@/test/mocks/i18n";
import type { ReorderRule } from "../api/reorder-rules";
import { ReorderRulesTable } from "./ReorderRulesTable";

// The API sends Numeric(12,3) as a string, whatever the TypeScript type says.
const rule = {
  id: "rule-1",
  organization_id: "org-1",
  product_template_id: "tpl-1",
  product_name: "Latte cups",
  uom_id: "uom-1",
  uom_symbol: "pcs",
  location_id: "loc-1",
  min_quantity: "20.000",
  max_quantity: "40.000",
  safety_stock: "10.000",
  preferred_partner_id: null,
  notes: null,
  created_at: null,
  updated_at: null,
} as unknown as ReorderRule;

function renderTable(rules: ReorderRule[]) {
  render(
    <ReorderRulesTable
      rules={rules}
      isLoading={false}
      alertByRule={new Map()}
      locationName={() => "Cold Storage"}
      partnerName={() => "—"}
      onEdit={vi.fn()}
      onDelete={vi.fn()}
      isFiltered={false}
      onCreate={vi.fn()}
      catalogEmpty={false}
    />,
  );
}

describe("ReorderRulesTable", () => {
  it("prints safety stock the way it prints min and max", () => {
    renderTable([rule]);

    const row = screen.getByText("Latte cups").closest("tr") as HTMLElement;
    // "20 | 40 | 10.000" — the third figure kept the padding the other two lose.
    expect(within(row).getByText("20")).toBeInTheDocument();
    expect(within(row).getByText("40")).toBeInTheDocument();
    expect(within(row).getByText("10")).toBeInTheDocument();
    expect(within(row).queryByText("10.000")).not.toBeInTheDocument();
  });

  it("writes a fractional safety stock with the reader's decimal mark", async () => {
    await withLanguage("pl", () => {
      renderTable([
        { ...rule, safety_stock: "12.500" } as unknown as ReorderRule,
      ]);

      const row = screen.getByText("Latte cups").closest("tr") as HTMLElement;
      expect(within(row).getByText("12,5")).toBeInTheDocument();
    });
  });
});
