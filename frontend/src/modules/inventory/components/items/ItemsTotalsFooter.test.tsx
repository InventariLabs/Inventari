import { render as renderWithProviders, screen } from "@/test/utils";
import { beforeEach, describe, it, expect, vi } from "vitest";

import ItemsTotalsFooter from "./ItemsTotalsFooter";
import type { ItemAggregates } from "@/types";

vi.mock("@/hooks/useMoney", () => ({
  useMoney: () => (value: number) => `${value.toFixed(2)} zł`,
}));

// The one switch every stock-value surface reads.
const showInventoryValue = vi.hoisted(() => ({ current: true }));
vi.mock("@/modules/shared/hooks/useShowInventoryValue", () => ({
  useShowInventoryValue: () => showInventoryValue.current,
}));

beforeEach(() => {
  showInventoryValue.current = true;
});

function aggregates(over: Partial<ItemAggregates> = {}): ItemAggregates {
  return {
    count: 42,
    product_count: 42,
    total_weight: 0,
    total_volume: 0,
    total_value: 65,
    value_source: "valuation_layers",
    unpriced_count: 0,
    excludes_module_items: false,
    excludes_unlisted_layers: false,
    ...over,
  };
}

/**
 * The ledger knows products, not shelves, so a filtered slice has
 * no ledger value. The footer used to print a number there anyway — the
 * shelf's stock priced at rates the organization's other receipts earned.
 * When the API withholds the figure, the footer says why instead.
 */
describe("ItemsTotalsFooter — the value it holds is the value the ledger holds", () => {
  it("renders the figure the API sends", () => {
    renderWithProviders(<ItemsTotalsFooter aggregates={aggregates()} />);

    expect(screen.getByText("65.00 zł")).toBeInTheDocument();
    expect(screen.queryByText(/filtered slice/i)).toBeNull();
  });

  it("names the module items a slice leaves to the statistics total", () => {
    // The default list leaves module-owned items to the module; the
    // statistics tile beside this footer sums the whole ledger. Two right
    // numbers about two different sets — silence read as an error.
    renderWithProviders(
      <ItemsTotalsFooter
        aggregates={aggregates({ excludes_module_items: true })}
      />,
    );

    expect(
      screen.getByText(/module data is not in this sum/i),
    ).toBeInTheDocument();
  });

  it("stays silent about module scoping when the sum covers everything", () => {
    renderWithProviders(<ItemsTotalsFooter aggregates={aggregates()} />);

    expect(screen.queryByText(/module data is not in this sum/i)).toBeNull();
  });

  it("says the ledger value is unavailable when the API sends none", () => {
    renderWithProviders(
      <ItemsTotalsFooter
        aggregates={aggregates({
          total_value: null,
          value_source: "not_available_under_filter",
        })}
      />,
    );

    expect(
      screen.getByText(/cost layers hold no value for a filtered slice/i),
    ).toBeInTheDocument();
    expect(screen.queryByText(/zł/)).toBeNull();
    // The count still describes the slice.
    expect(screen.getByText("42 positions")).toBeInTheDocument();
  });

  it("does not dress the withheld value up as a zero", () => {
    renderWithProviders(
      <ItemsTotalsFooter
        aggregates={aggregates({
          total_value: null,
          value_source: "not_available_under_filter",
        })}
      />,
    );

    expect(screen.queryByText("0.00 zł")).toBeNull();
  });

  it("keeps the unpriced sentence beside a standing value only", () => {
    const standing = renderWithProviders(
      <ItemsTotalsFooter aggregates={aggregates({ unpriced_count: 3 })} />,
    );
    expect(
      screen.getByText(/3 positions have no cost history/i),
    ).toBeInTheDocument();
    standing.unmount();

    renderWithProviders(
      <ItemsTotalsFooter
        aggregates={aggregates({
          total_value: null,
          value_source: "not_available_under_filter",
          unpriced_count: 3,
        })}
      />,
    );
    // No value stands, so "left out of the value" names nothing.
    expect(screen.queryByText(/no cost history/i)).toBeNull();
  });
});

describe("ItemsTotalsFooter — every reason the sum is smaller", () => {
  /**
   * Two things put the footer below the statistics tile: stock a vertical
   * module owns, and cost the ledger holds for a product with no position
   * on this list. With only the first sentence available, a footer showing
   * it while both were true implied it explained the whole difference.
   */
  it("names a ledger layer whose product has no position here", () => {
    renderWithProviders(
      <ItemsTotalsFooter
        aggregates={aggregates({ excludes_unlisted_layers: true })}
      />,
    );

    expect(
      screen.getByText(/statistics total counts it|kafelek statystyk/i),
    ).toBeInTheDocument();
  });

  it("says both sentences when both are true", () => {
    renderWithProviders(
      <ItemsTotalsFooter
        aggregates={aggregates({
          excludes_module_items: true,
          excludes_unlisted_layers: true,
        })}
      />,
    );

    expect(
      screen.getByText(/module data is not in this sum/i),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/products with no position here/i),
    ).toBeInTheDocument();
  });
});

/**
 * A litre is not a kilogram. The aggregates used to return one number that
 * summed both, and the footer labelled it kg: 2 l of milk read "2,0 kg".
 * The API now sends the volume apart from the weight, and each figure
 * stands under its own unit — a litre-only list shows no kilogram total.
 */
describe("ItemsTotalsFooter — litres are not kilograms", () => {
  it("shows a litre-only set in litres, with no kilogram total", () => {
    renderWithProviders(
      <ItemsTotalsFooter
        aggregates={aggregates({ total_weight: 0, total_volume: 2 })}
      />,
    );

    expect(screen.getByText("2.0 l")).toBeInTheDocument();
    expect(screen.queryByText(/kg/)).toBeNull();
  });

  it("keeps the two sums apart when the list holds both", () => {
    renderWithProviders(
      <ItemsTotalsFooter
        aggregates={aggregates({ total_weight: 1.5, total_volume: 2 })}
      />,
    );

    expect(screen.getByText("1.5 kg")).toBeInTheDocument();
    expect(screen.getByText("2.0 l")).toBeInTheDocument();
  });
});

/**
 * The value is a business metric. The home profile presets the signal off
 * through `stats.show_inventory_value`, and the footer kept talking to it
 * about cost layers and directed it to a figure the profile does not show
 * and the organization keeps no prices for.
 */
describe("ItemsTotalsFooter — a profile that does not show stock value", () => {
  beforeEach(() => {
    showInventoryValue.current = false;
  });

  it("keeps the count and the weight, and drops every word about value", () => {
    renderWithProviders(
      <ItemsTotalsFooter
        aggregates={aggregates({
          total_weight: 12.5,
          total_value: null,
          value_source: "not_available_under_filter",
          unpriced_count: 3,
          excludes_module_items: true,
          excludes_unlisted_layers: true,
        })}
      />,
    );

    expect(screen.getByText("42 positions")).toBeInTheDocument();
    expect(screen.getByText("12.5 kg")).toBeInTheDocument();
    expect(
      screen.queryByText(/cost layers|cost history|filtered slice|ledger/i),
    ).toBeNull();
  });

  it("does not print the standing figure either", () => {
    renderWithProviders(<ItemsTotalsFooter aggregates={aggregates()} />);

    expect(screen.queryByText("65.00 zł")).toBeNull();
    expect(screen.getByText("42 positions")).toBeInTheDocument();
  });
});
