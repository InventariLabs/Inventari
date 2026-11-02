import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, within } from "@/test/utils";
import { DocumentValueTotals } from "./DocumentValueTotals";
import * as organizationHooks from "@/modules/settings/hooks/useOrganization";
import type { WarehouseDocument } from "@/modules/warehouse/types";
import type { Organization } from "@/types";

// The data sources are mocked. useDocumentCurrency and
// useOrganizationCurrency run for real, so the tests below see the whole
// resolution chain (document currency → organization currency → fallback)
// instead of a stub standing in for it. The profile stands in as the one
// that decides whether money belongs on this screen at all.
vi.mock("@/modules/settings/hooks/useOrganization", async () => {
  const actual = await vi.importActual<typeof organizationHooks>(
    "@/modules/settings/hooks/useOrganization",
  );
  return { ...actual, useOrganization: vi.fn() };
});

let valueTracking = true;
vi.mock("@/modules/warehouse/hooks/useDocumentProfile", () => ({
  useDocumentProfile: () => ({
    data: { value_tracking_enabled: valueTracking },
  }),
}));

const mockedUseOrganization = vi.mocked(organizationHooks.useOrganization);

function setOrganizationCurrency(currency: string | null) {
  mockedUseOrganization.mockReturnValue({
    data:
      currency === null
        ? undefined
        : ({ id: "org-1", name: "Acme", currency } as Organization),
  } as unknown as ReturnType<typeof organizationHooks.useOrganization>);
}

const makeDoc = (
  overrides: Partial<WarehouseDocument> = {},
): WarehouseDocument =>
  ({
    id: "doc-1",
    number: "IN/2026/001",
    type: "IN",
    status: "DRAFT",
    total_net: 100.0,
    total_tax: 23.0,
    total_gross: 123.0,
    currency: "PLN",
    ...overrides,
  }) as WarehouseDocument;

describe("DocumentValueTotals", () => {
  beforeEach(() => {
    valueTracking = true;
    setOrganizationCurrency("PLN");
  });

  it("renders nothing when no totals", () => {
    const doc = makeDoc();
    doc.total_net = null;
    doc.total_gross = null;
    const { container } = render(<DocumentValueTotals document={doc} />);
    expect(container.querySelector("dl")).not.toBeInTheDocument();
  });

  it("renders nothing for a transfer, whatever its totals hold", () => {
    // A move between shelves changes where the goods stand, not what they
    // are worth; its form asks for no price, so no card quotes one back.
    const { container } = render(
      <DocumentValueTotals document={makeDoc({ type: "INT" })} />,
    );

    expect(container.querySelector("dl")).not.toBeInTheDocument();
  });

  it("states what a write-off cost, though no price was typed on it", () => {
    render(
      <DocumentValueTotals
        document={makeDoc({
          type: "SCRAP",
          total_net: "25.00",
          total_tax: null,
          total_gross: "25.00",
        })}
      />,
    );

    expect(screen.getByText("Cost of the write-off")).toBeInTheDocument();
    expect(screen.getByText("PLN 25.00")).toBeInTheDocument();
    expect(screen.queryByText("Tax Total")).not.toBeInTheDocument();
  });

  it("says nothing about a write-off the cost layers could not value", () => {
    const { container } = render(
      <DocumentValueTotals
        document={makeDoc({
          type: "SCRAP",
          total_net: null,
          total_tax: null,
          total_gross: null,
        })}
      />,
    );

    expect(container).toBeEmptyDOMElement();
  });

  it("renders nothing while the profile does not track value", () => {
    valueTracking = false;

    const { container } = render(<DocumentValueTotals document={makeDoc()} />);

    expect(container.querySelector("dl")).not.toBeInTheDocument();
  });

  it("renders net, tax and gross with the document currency", () => {
    render(<DocumentValueTotals document={makeDoc()} />);

    expect(screen.getByText("Net Total")).toBeInTheDocument();
    expect(screen.getByText("PLN 100.00")).toBeInTheDocument();
    expect(screen.getByText("Tax Total")).toBeInTheDocument();
    expect(screen.getByText("PLN 23.00")).toBeInTheDocument();
    expect(screen.getByText("Gross Total")).toBeInTheDocument();
    expect(screen.getByText("PLN 123.00")).toBeInTheDocument();
  });

  it("hides tax row when total_tax is null", () => {
    render(<DocumentValueTotals document={makeDoc({ total_tax: null })} />);

    expect(screen.getByText("Net Total")).toBeInTheDocument();
    expect(screen.getByText("Gross Total")).toBeInTheDocument();
    expect(screen.queryByText("Tax Total")).not.toBeInTheDocument();
  });

  it("renders when only total_gross is set", () => {
    render(
      <DocumentValueTotals
        document={makeDoc({ total_net: null, total_gross: "50" })}
      />,
    );

    expect(screen.getByText("PLN 50.00")).toBeInTheDocument();
  });

  it("prefers the document currency over the organization currency", () => {
    setOrganizationCurrency("PLN");

    render(<DocumentValueTotals document={makeDoc({ currency: "EUR" })} />);

    expect(screen.getByText("€123.00")).toBeInTheDocument();
    expect(screen.queryByText("PLN 123.00")).not.toBeInTheDocument();
  });

  it("falls back to the organization currency when the document has none", () => {
    setOrganizationCurrency("EUR");

    render(<DocumentValueTotals document={makeDoc({ currency: null })} />);

    expect(screen.getByText("€100.00")).toBeInTheDocument();
    expect(screen.getByText("€23.00")).toBeInTheDocument();
    expect(screen.getByText("€123.00")).toBeInTheDocument();
  });

  it("marks the amounts as unsigned when neither the document nor the organization names a currency", () => {
    setOrganizationCurrency(null);

    render(<DocumentValueTotals document={makeDoc({ currency: null })} />);

    // The third leg of the resolution chain is reachable now that the
    // organization hook stopped inventing "USD": an amount whose currency
    // nobody set carries a question mark rather than a wrong symbol.
    expect(screen.getByText("100.00 ?")).toBeInTheDocument();
    expect(screen.queryByText("$100.00")).toBeNull();
  });

  it("lists the tax per rate when the lines carry two rates", () => {
    const line = (rate: string, net: string, tax: string) => ({
      tax_rate: rate,
      line_value: net,
      line_tax: tax,
    });
    render(
      <DocumentValueTotals
        document={makeDoc({
          currency: "EUR",
          total_net: "125.00",
          total_tax: "20.75",
          total_gross: "145.75",
          lines: [
            line("19.00", "100.00", "19.00"),
            line("7.00", "25.00", "1.75"),
          ] as unknown as WarehouseDocument["lines"],
        })}
      />,
    );

    const table = screen.getByRole("table", { name: "Tax by rate" });
    const rows = within(table).getAllByRole("row");
    expect(rows.map((row) => row.textContent)).toEqual([
      "RateNet TotalTax Total",
      "19%€100.00€19.00",
      "7%€25.00€1.75",
    ]);
  });

  it("labels a fractional rate with its digits", () => {
    render(
      <DocumentValueTotals
        document={makeDoc({
          currency: "EUR",
          lines: [
            { tax_rate: "20.00", line_value: "100.00", line_tax: "20.00" },
            { tax_rate: "5.50", line_value: "100.00", line_tax: "5.50" },
          ] as unknown as WarehouseDocument["lines"],
        })}
      />,
    );

    const table = screen.getByRole("table", { name: "Tax by rate" });
    expect(
      within(table).getByRole("rowheader", { name: "5.5%" }),
    ).toBeVisible();
    expect(within(table).getByRole("rowheader", { name: "20%" })).toBeVisible();
  });

  it("prints no table for a single rate, which the totals already state", () => {
    render(
      <DocumentValueTotals
        document={makeDoc({
          lines: [
            { tax_rate: "23.00", line_value: "100.00", line_tax: "23.00" },
          ] as unknown as WarehouseDocument["lines"],
        })}
      />,
    );

    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });
});
