import { beforeEach, describe, expect, it, vi } from "vitest";
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithProviders } from "@/test/utils";
import { LotTrace } from "./LotTrace";

const { trace, exportTrace } = vi.hoisted(() => ({
  trace: vi.fn(),
  exportTrace: vi.fn(),
}));

vi.mock("@/lib/api/stockLots", () => ({
  stockLotsApi: { trace, exportTrace },
}));

const downloadBlob = vi.hoisted(() => vi.fn());
vi.mock("@/utils/helpers", () => ({ downloadBlob }));

const FLOUR = {
  lot_id: "flour",
  lot_name: "F-01",
  product_name: "Rye flour",
  uom_symbol: "kg",
  expiry_date: null,
  made_from_lot_id: null,
  received: [
    {
      direction: "in",
      reference_type: "document",
      reference_id: "receipt",
      label: "GR/0001",
      partner_id: "p1",
      partner_name: "Grain Co",
      partner_address: "1 Field Rd, Leeds",
      moved_at: "2026-09-01T10:00:00Z",
      quantity: "100.000",
      produced: [],
    },
  ],
  sent: [
    {
      direction: "out",
      reference_type: "maker_production",
      reference_id: "run",
      label: "PR/2026/0001",
      partner_id: null,
      partner_name: null,
      partner_address: null,
      moved_at: "2026-09-04T10:00:00Z",
      quantity: "20.000",
      produced: [
        {
          lot_id: "bread",
          lot_name: "B-01",
          product_name: "Rye bread",
          uom_symbol: "pcs",
          quantity: "50.000",
        },
      ],
    },
  ],
};

const BREAD = {
  lot_id: "bread",
  lot_name: "B-01",
  product_name: "Rye bread",
  uom_symbol: "pcs",
  expiry_date: null,
  made_from_lot_id: "flour",
  received: [],
  sent: [
    {
      direction: "out",
      reference_type: "document",
      reference_id: "delivery",
      label: "DN/0008",
      partner_id: "p2",
      partner_name: "Corner Shop",
      partner_address: null,
      moved_at: "2026-09-06T10:00:00Z",
      quantity: "12.000",
      produced: [],
    },
  ],
};

describe("LotTrace", () => {
  beforeEach(() => {
    trace.mockReset();
    exportTrace.mockReset();
    downloadBlob.mockReset();
    trace.mockResolvedValue({
      lot_id: "flour",
      lots: [FLOUR, BREAD],
      truncated: false,
    });
  });

  it("names the supplier, the date and the quantity of what came in", async () => {
    renderWithProviders(<LotTrace lotId="flour" />);

    const row = (await screen.findByText("Grain Co")).closest("li");
    expect(row).not.toBeNull();
    const cell = within(row as HTMLElement);
    expect(cell.getByText("GR/0001")).toBeInTheDocument();
    expect(cell.getByText("1 Field Rd, Leeds")).toBeInTheDocument();
    expect(cell.getByText(/100/)).toBeInTheDocument();
  });

  it("leads a production run to the batch it made, and that batch's customers", async () => {
    renderWithProviders(<LotTrace lotId="flour" />);

    const made = await screen.findAllByRole("link", { name: "B-01" });
    expect(made[0]).toHaveAttribute("href", "/inventory/lots/bread");
    // The bread's own step forward follows the flour's.
    expect(screen.getByText("Corner Shop")).toBeInTheDocument();
    expect(screen.getByText("DN/0008")).toBeInTheDocument();
    expect(screen.getByText(/F-01/)).toBeInTheDocument();
  });

  it("says when the walk stopped before the end", async () => {
    trace.mockResolvedValue({
      lot_id: "flour",
      lots: [FLOUR],
      truncated: true,
    });

    renderWithProviders(<LotTrace lotId="flour" />);

    expect(
      await screen.findByText(/more batches were made from this one/i),
    ).toBeInTheDocument();
  });

  it("hands the trace over as a spreadsheet", async () => {
    const blob = new Blob(["x"]);
    exportTrace.mockResolvedValue(blob);
    renderWithProviders(<LotTrace lotId="flour" />);

    await screen.findByText("Grain Co");
    await userEvent.click(screen.getByRole("button", { name: /export/i }));

    expect(exportTrace).toHaveBeenCalledWith("flour");
    expect(downloadBlob).toHaveBeenCalledWith(
      blob,
      expect.stringMatching(/^batch_trace_.*\.xlsx$/),
    );
  });
});
