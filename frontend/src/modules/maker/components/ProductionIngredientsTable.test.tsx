import { describe, it, expect, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import type {
  CostBreakdownEntry,
  ShortageEntry,
  ProductionOrderLine,
} from "@/modules/maker/types/maker";
import { ProductionIngredientsTable } from "./ProductionIngredientsTable";

const entry: CostBreakdownEntry = {
  child_template_id: "tpl-wax",
  child_template_name: "Soy wax",
  consumed_qty: "200",
  unit: "kg",
  unit_cost: "45",
  cost: "9000",
  percentage_of_total: "100",
  cost_source: "avco",
};

const line: ProductionOrderLine = {
  id: "line-1",
  child_template_id: "tpl-wax",
  child_template_name: "Soy wax",
  consumed_qty: "200",
  unit: "kg",
  source_location_id: null,
  source_location_name: null,
  unit_cost_snapshot: "45",
  cost_source: "avco",
} as unknown as ProductionOrderLine;

function short(over: string | null): ShortageEntry {
  return {
    child_template_id: "tpl-wax",
    child_template_name: "Soy wax",
    needed: "200",
    available: "6",
    shortage: over,
    uom_symbol: "kg",
    convertible: true,
    available_uom_symbol: "kg",
  };
}

const t = (key: string, opts?: Record<string, unknown>) => {
  if (key.startsWith("detail.plannedShortageHint"))
    return `Planned consumption exceeds stock — ${opts?.count}`;
  if (key === "detail.line.shortLabel") return "short";
  if (key === "detail.line.unmeasurableShort")
    return "short — units cannot be compared with stock";
  // Unit symbols resolve through common:units.<symbol> with the symbol as
  // the default; a stub that echoed the key would corrupt every quantity.
  if (key.startsWith("common:units.")) return String(opts?.defaultValue ?? key);
  return key;
};

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t, i18n: { language: "en" } }),
}));
vi.mock("@/hooks/useOrganizationCurrency", () => ({
  useOrganizationCurrency: () => "USD",
}));

const UNIT_HEADER = "detail.line.unitCost";
const LINE_HEADER = "detail.line.lineCost";

describe("ProductionIngredientsTable — a phone reads each ingredient as a card", () => {
  it("gives the name a line of its own and labels every figure", () => {
    const longName =
      "A very long ingredient name that would overflow on narrow screens";
    const line: ProductionOrderLine = {
      id: "l1",
      production_order_id: "order-1",
      child_template_id: "t1",
      child_template_name: longName,
      consumed_qty: "1000",
      unit: "kg",
      unit_cost_snapshot: "12.50",
      cost_source: "avco",
      source_location_id: null,
      source_location_name: null,
    };
    render(<ProductionIngredientsTable lines={[line]} />);
    const row = screen.getByTestId("maker-ingredient-row");
    // Four columns on 390 px clipped the name to one letter: on a phone it
    // spans the card and wraps, and only from sm up does it become a column.
    const name = within(row).getByText(longName);
    expect(name).toHaveClass("col-span-3", "break-words", "sm:col-span-1");
    expect(name).not.toHaveClass("truncate");
    // The header row is a desktop thing, so each figure names itself there.
    for (const key of ["detail.line.qty", UNIT_HEADER, LINE_HEADER]) {
      expect(within(row).getByText(t(key))).toHaveClass("sm:hidden");
    }
  });
});

describe("ProductionIngredientsTable — one header, one meaning", () => {
  it("shows rate and line amount under their own named columns in a draft", () => {
    render(
      <ProductionIngredientsTable
        lines={[]}
        isPlanned
        planned={[entry]}
        shortages={new Map()}
      />,
    );
    // The rate and the amount are both present and both named.
    expect(screen.getAllByText(t(UNIT_HEADER))[0]).toBeInTheDocument();
    expect(screen.getAllByText(t(LINE_HEADER))[0]).toBeInTheDocument();
    expect(screen.getByText("$45.00")).toBeInTheDocument();
    expect(screen.getByText("$9,000.00")).toBeInTheDocument();
  });

  it("gives a closed run the same two named columns from its lines", () => {
    render(<ProductionIngredientsTable lines={[line]} isPlanned={false} />);
    expect(screen.getAllByText(t(UNIT_HEADER))[0]).toBeInTheDocument();
    expect(screen.getAllByText(t(LINE_HEADER))[0]).toBeInTheDocument();
    expect(screen.getByText("$45.00")).toBeInTheDocument();
    // 200 kg at $45 — the line amount, not a rate in its place.
    expect(screen.getByText("$9,000.00")).toBeInTheDocument();
    expect(screen.getByText(t("costSource.avco"))).toBeInTheDocument();
  });

  it("never prints the raw cost-source word for a line with no cost", () => {
    const unpriced = {
      ...line,
      unit_cost_snapshot: null,
      cost_source: "none",
    } as unknown as ProductionOrderLine;
    render(<ProductionIngredientsTable lines={[unpriced]} isPlanned={false} />);
    expect(screen.queryByText("none")).not.toBeInTheDocument();
    expect(screen.getByText(t("costSource.none"))).toBeInTheDocument();
  });

  it("keeps column meanings consistent between DRAFT and COMPLETED", () => {
    // Same numbers, two states: the draft used to print the line amount
    // under "UNIT COST", so closing the run read as a hundredfold saving.
    const draft = render(
      <ProductionIngredientsTable
        lines={[]}
        isPlanned
        planned={[entry]}
        shortages={new Map()}
      />,
    );
    const draftHead = screen.getAllByText(t(UNIT_HEADER))[0].textContent;
    const draftValues = [
      screen.getByText("$45.00"),
      screen.getByText("$9,000.00"),
    ];
    draft.unmount();

    render(<ProductionIngredientsTable lines={[line]} isPlanned={false} />);
    // Same headers, same values under them.
    expect(screen.getAllByText(t(UNIT_HEADER))[0].textContent).toBe(draftHead);
    expect(screen.getByText("$45.00").textContent).toBe(
      draftValues[0].textContent,
    );
    expect(screen.getByText("$9,000.00").textContent).toBe(
      draftValues[1].textContent,
    );
  });

  it("names the shortage next to the number instead of staying silent", () => {
    render(
      <ProductionIngredientsTable
        lines={[]}
        isPlanned
        planned={[entry]}
        shortages={new Map([["tpl-wax", short("194")]])}
      />,
    );
    expect(screen.getByTestId("maker-planned-short")).toHaveTextContent(
      "short 194 kg",
    );
    expect(
      screen.getByText(/planned consumption exceeds stock/i),
    ).toBeInTheDocument();
  });

  it("says so when the units cannot be compared", () => {
    render(
      <ProductionIngredientsTable
        lines={[]}
        isPlanned
        planned={[entry]}
        shortages={new Map([["tpl-wax", short(null)]])}
      />,
    );
    expect(screen.getByTestId("maker-planned-short")).toHaveTextContent(
      /cannot be compared/i,
    );
  });

  it("keeps the plain forecast when everything is covered", () => {
    render(
      <ProductionIngredientsTable
        lines={[]}
        isPlanned
        planned={[entry]}
        shortages={new Map()}
      />,
    );
    expect(screen.queryByTestId("maker-planned-short")).not.toBeInTheDocument();
    expect(
      screen.queryByText(/planned consumption exceeds stock/i),
    ).not.toBeInTheDocument();
  });
});

/**
 * A closed run's consumption is stored twice: on the line at numeric(12,4)
 * and in the moves ledger at numeric(12,3). The order page prints both, one
 * above the other, so a reader saw "3.2288 kg" and "3.229 kg" for the same
 * event with nothing saying which to trust. The ledger is what the reader
 * compares against, so the table reads at the ledger's own scale.
 */
describe("ProductionIngredientsTable — the consumption reads like the move it wrote", () => {
  const fractionalLine = {
    ...line,
    consumed_qty: "3.2288",
  } as ProductionOrderLine;
  const fractionalEntry = { ...entry, consumed_qty: "3.2288" };

  it("a closed run's line reads at the move's scale (3.229, not 3.2288)", () => {
    render(
      <ProductionIngredientsTable lines={[fractionalLine]} isPlanned={false} />,
    );
    expect(screen.getByText("3.229 kg")).toBeInTheDocument();
    expect(screen.queryByText("3.2288 kg")).not.toBeInTheDocument();
  });

  it("a draft's planned consumption reads at the same scale", () => {
    render(
      <ProductionIngredientsTable
        lines={[]}
        isPlanned
        planned={[fractionalEntry]}
        shortages={new Map()}
      />,
    );
    expect(screen.getByText("3.229 kg")).toBeInTheDocument();
  });

  it("values under three decimals are not padded", () => {
    const twoDecimals = {
      ...line,
      consumed_qty: "2.5",
    } as ProductionOrderLine;
    render(
      <ProductionIngredientsTable lines={[twoDecimals]} isPlanned={false} />,
    );
    expect(screen.getByText("2.5 kg")).toBeInTheDocument();
  });
});

describe("ProductionIngredientsTable — a run recorded after the fact", () => {
  it("names what the records did not hold on the line", () => {
    render(
      <ProductionIngredientsTable
        lines={[{ ...line, shortfall_qty: "4.0000" }]}
        isPlanned={false}
      />,
    );
    expect(screen.getByTestId("maker-line-shortfall")).toHaveTextContent(
      "detail.line.shortfall",
    );
  });

  it("says nothing on a line drawn in full", () => {
    render(<ProductionIngredientsTable lines={[line]} isPlanned={false} />);
    expect(
      screen.queryByTestId("maker-line-shortfall"),
    ).not.toBeInTheDocument();
  });
});
