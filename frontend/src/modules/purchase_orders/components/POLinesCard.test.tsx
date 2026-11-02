import { afterEach, beforeEach, describe, it, expect, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import { POLinesCard } from "./POLinesCard";
import { tFor, withLanguage } from "@/test/mocks/i18n";
import { formatMoney } from "@/utils/formatters";

/** toHaveTextContent folds the non-breaking spaces Intl writes; fold ours too. */
const pln = (value: number) =>
  formatMoney(value, "PLN", "pl").replace(/\s+/g, " ");
import type {
  POLine,
  POStatus,
} from "@/modules/purchase_orders/types/purchase-orders";

function line(over: Partial<POLine> = {}): POLine {
  return {
    id: "line-1",
    purchase_order_id: "po-1",
    product_template_id: null,
    name: "Dell Latitude 5540",
    quantity_ordered: "4.000",
    quantity_received: "0.000",
    unit_price: "4200.00",
    uom_id: null,
    uom_symbol: "pcs",
    tax_rate: "23.00",
    line_number: 1,
    notes: null,
    ...over,
  };
}

function renderCard(lines: POLine[], status: POStatus = "CONFIRMED") {
  render(
    <POLinesCard
      lines={lines}
      poNet={16800}
      poTax={3864}
      poTotal={20664}
      currency="PLN"
      locale="pl"
      status={status}
      t={tFor("purchase_orders")}
    />,
  );
}

/**
 * The line's tax rate is read off the wire and was printed as JavaScript
 * writes numbers — a fractional rate showed a dot on a Polish screen, in the
 * same parentheses as the amounts that already used the reader's mark.
 */
describe("POLinesCard — the tax rate speaks the reader's mark", () => {
  it("writes the rate with the language's decimal mark", async () => {
    await withLanguage("pl", () => {
      renderCard([line()]);

      expect(screen.getByText(/23,0%/)).toBeInTheDocument();
      expect(screen.queryByText(/23\.0%/)).not.toBeInTheDocument();
    });
  });

  it("rounds no fraction of the rate away", async () => {
    await withLanguage("pl", () => {
      renderCard([line({ tax_rate: "7.70" })]);

      expect(screen.getByText(/7,7%/)).toBeInTheDocument();
    });
  });

  /**
   * The rate on an order line is a number somebody checks against the
   * invoice. formatPercentLocale fixed its decimal count to the one the call
   * site named, so the wire's 20.75 read "20,8%" — a rate nobody put there.
   */
  it("keeps every digit of a fractional rate", async () => {
    await withLanguage("pl", () => {
      renderCard([line({ tax_rate: "20.75" })]);

      expect(screen.getByText(/20,75%/)).toBeInTheDocument();
      expect(screen.queryByText(/20,8%/)).not.toBeInTheDocument();
    });
  });
});

/**
 * The quantity and its unit, as the reader's language writes them.
 *
 * The card printed both as they arrive: "4.000 pcs" — three decimals on a
 * unit that has none, an English symbol beside a list that says "szt.", and
 * an English decimal point next to "14,00 USD" in the same row.
 */
describe("POLinesCard — the quantity and the unit read as one row", () => {
  it("writes four pieces as the reader counts them", async () => {
    await withLanguage("pl", () => {
      renderCard([line({ quantity_ordered: "4.000", uom_symbol: "pcs" })]);

      expect(screen.getByText(/^4$/)).toBeInTheDocument();
      expect(screen.getAllByText("szt.").length).toBeGreaterThan(0);
      expect(screen.queryByText("4.000")).not.toBeInTheDocument();
      expect(screen.queryByText("pcs")).not.toBeInTheDocument();
    });
  });
});

/**
 * The receipt progress was gated by `line.quantity_received <
 * line.quantity_ordered` — text against text, so "3.000" < "10.000" was
 * false. A line received three of ten drew neither the bar nor the pair of
 * numbers, while three of four drew both, and the reader of a partly received
 * large line saw no trace that anything had arrived. The quantities travel as
 * text; this gate was the one place in the card that forgot to read them as
 * numbers before comparing.
 */
describe("POLinesCard — a line received three of ten says so", () => {
  it("draws one meter per partly received line, whatever the magnitudes", async () => {
    await withLanguage("pl", () => {
      renderCard([
        line({
          id: "large",
          quantity_ordered: "10.000",
          quantity_received: "3.000",
        }),
        line({
          id: "small",
          quantity_ordered: "4.000",
          quantity_received: "3.000",
        }),
      ]);

      expect(screen.getAllByRole("meter")).toHaveLength(2);
    });
  });

  it("names both numbers the large line compares", async () => {
    await withLanguage("pl", () => {
      renderCard([
        line({
          id: "large",
          quantity_ordered: "10.000",
          quantity_received: "3.000",
        }),
      ]);

      expect(screen.getByText("3/10")).toBeInTheDocument();
    });
  });

  /**
   * The meter's label interpolated the wire's own strings, so a screen
   * reader was told "Przyjęto 3.000 z 10.000" — three thousand received of
   * ten thousand — about a line where three of ten had arrived.
   */
  it("writes the two numbers the meter names the reader's way", async () => {
    await withLanguage("pl", () => {
      renderCard([
        line({
          quantity_ordered: "10.000",
          quantity_received: "3.000",
        }),
      ]);

      expect(screen.getByRole("meter")).toHaveAttribute(
        "aria-label",
        "Przyjęto 3 z 10",
      );
    });
  });
});

/**
 * The line used to be a sentence: the name at the left edge, and at the
 * right one "4 200,00 zł / szt. = 20 664,00 zł (Netto: 16 800,00 zł +
 * 23,0% = 3 864,00 zł)" — whose second half read as if the net plus the rate
 * came to the tax. Every amount has a column now, the way the document
 * detail lays out its lines.
 */
describe("POLinesCard — the lines read as columns", () => {
  const cellUnder = (header: string) => {
    const table = screen.getByRole("table");
    const headers = within(table)
      .getAllByRole("columnheader")
      .map((h) => h.textContent?.trim());
    const column = headers.indexOf(header);
    expect(column, `no "${header}" column in ${headers.join(", ")}`).not.toBe(
      -1,
    );
    const [, firstLine] = within(table).getAllByRole("row");
    return within(firstLine).getAllByRole("cell")[column];
  };

  it("gives the net, the tax and the total a column each", async () => {
    await withLanguage("pl", () => {
      renderCard([line()]);

      expect(cellUnder("Netto")).toHaveTextContent(pln(16800));
      const tax = cellUnder("VAT");
      expect(tax).toHaveTextContent(pln(3864));
      expect(tax).toHaveTextContent("23,0%");
      expect(cellUnder("Suma")).toHaveTextContent(pln(20664));
      expect(cellUnder("Cena netto")).toHaveTextContent(pln(4200));
    });
  });

  it("writes no sum that reads as net plus a rate", async () => {
    await withLanguage("pl", () => {
      renderCard([line()]);

      expect(screen.queryByText(/\+\s*23,0%\s*=/)).not.toBeInTheDocument();
    });
  });

  it("shows how much arrived only once something could have", async () => {
    await withLanguage("pl", () => {
      renderCard([line()], "DRAFT");

      const headers = within(screen.getByRole("table"))
        .getAllByRole("columnheader")
        .map((h) => h.textContent?.trim());
      expect(headers).not.toContain("Przyjęto");
    });
  });
});

describe("POLinesCard — a line with no price", () => {
  it("says the total is not known instead of printing a sum", () => {
    render(
      <POLinesCard
        lines={[line({ unit_price: null })]}
        poNet={0}
        poTax={0}
        poTotal={0}
        totalKnown={false}
        currency="PLN"
        locale="pl"
        status="DRAFT"
        t={tFor("purchase_orders")}
      />,
    );

    expect(screen.getByText("No price yet")).toBeInTheDocument();
    expect(screen.queryByText(/^Net.*:$/)).not.toBeInTheDocument();
    // Nor does the line itself claim to be worth nothing.
    expect(screen.queryByText(/0,00/)).not.toBeInTheDocument();
  });
});

describe("POLinesCard — on a phone", () => {
  const originalMatchMedia = window.matchMedia;

  beforeEach(() => {
    window.matchMedia = vi.fn().mockImplementation((query: string) => ({
      matches: query.includes("max-width"),
      media: query,
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    }));
  });

  afterEach(() => {
    window.matchMedia = originalMatchMedia;
  });

  it("lists the lines instead of squeezing seven columns into 390 px", async () => {
    await withLanguage("pl", () => {
      renderCard([line()]);

      expect(screen.queryByRole("table")).not.toBeInTheDocument();
      const [only] = screen.getAllByRole("listitem");
      expect(only).toHaveTextContent("Dell Latitude 5540");
      expect(only).toHaveTextContent(pln(20664));
    });
  });
});
