import { describe, expect, it, vi } from "vitest";
import userEvent from "@testing-library/user-event";
import { render, screen, within } from "@/test/utils";
import { withLanguage } from "@/test/mocks/i18n";
import type { ReorderRule } from "../api/reorder-rules";
import { ReorderRulesTable } from "./ReorderRulesTable";

const phone = vi.hoisted(() => ({ value: false }));
vi.mock("@/hooks/useMediaQuery", () => ({
  useMediaQuery: () => phone.value,
}));

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

function renderTable(
  rules: ReorderRule[],
  handlers: { onEdit?: () => void; onDelete?: () => void } = {},
) {
  render(
    <ReorderRulesTable
      rules={rules}
      isLoading={false}
      alertByRule={new Map()}
      locationName={() => "Cold Storage"}
      partnerName={() => "—"}
      onEdit={handlers.onEdit ?? vi.fn()}
      onDelete={handlers.onDelete ?? vi.fn()}
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

describe("ReorderRulesTable with no rules yet", () => {
  const renderEmpty = (catalogEmpty: boolean) =>
    render(
      <ReorderRulesTable
        rules={[]}
        isLoading={false}
        alertByRule={new Map()}
        locationName={() => "Cold Storage"}
        partnerName={() => "—"}
        onEdit={vi.fn()}
        onDelete={vi.fn()}
        isFiltered={false}
        onCreate={vi.fn()}
        catalogEmpty={catalogEmpty}
      />,
    );

  it("does not send an organization that has products to add products first", () => {
    renderEmpty(false);

    expect(screen.queryByText(/Add products in Inventory first/)).toBeNull();
    const add = screen.getByRole("button", { name: /Add rule/ });
    expect(add).toBeEnabled();
    // An outline: the page header already holds the filled "Add rule".
    expect(add).toHaveClass("border");
    expect(add).not.toHaveClass("bg-primary-700");
  });

  it("sends an organization with no products to Inventory", () => {
    renderEmpty(true);

    expect(
      screen.getByText(/Add products in Inventory first/),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Add rule/ })).toBeNull();
  });
});

describe("ReorderRulesTable on a phone", () => {
  it("lists a rule as a card with every figure and its actions in view", async () => {
    phone.value = true;
    try {
      const onEdit = vi.fn();
      renderTable(
        [
          {
            ...rule,
            preferred_partner_id: "p-1",
          } as unknown as ReorderRule,
        ],
        { onEdit },
      );

      expect(screen.queryByRole("table")).not.toBeInTheDocument();
      const card = screen.getByText("Latte cups").closest("li") as HTMLElement;
      expect(within(card).getByText("Safety stock")).toBeInTheDocument();
      expect(within(card).getByText(/Preferred supplier/)).toBeInTheDocument();
      await userEvent.click(
        within(card).getByRole("button", { name: "Edit Latte cups" }),
      );
      expect(onEdit).toHaveBeenCalledOnce();
      const del = within(card).getByRole("button", {
        name: "Delete Latte cups",
      });
      // A thumb needs the 44 px floor, not the table's compact 32 px.
      expect(del).toHaveClass("h-11", "w-11");
      expect(del).not.toHaveClass("h-8");
      expect(
        within(card).getByRole("button", { name: "Edit Latte cups" }),
      ).toHaveClass("h-11", "w-11");
    } finally {
      phone.value = false;
    }
  });
});
