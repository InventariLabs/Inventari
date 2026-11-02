import { describe, expect, it } from "vitest";
import { withLanguage } from "@/test/mocks/i18n";
import { render, screen, within } from "@testing-library/react";
import StockReconciliationPanel from "./StockReconciliationPanel";
import type { Reconciliation } from "../types/analytics";

/**
 * The read-model measured three pairs and the response carried one, so the
 * warning admins receive named counts that no screen could show. These tests
 * hold the screen to both pairs that remain, and to the difference between a
 * figure of nought and a figure the server did not send.
 */
const base: Reconciliation = {
  items_scanned: 11,
  quant_move_drift_count: 0,
  quant_move_drift_total: "0.000",
  layer_quant_drift_count: 0,
  layer_quant_drift_total: "0.000",
};

function renderPanel(data: Partial<Reconciliation> = {}) {
  return render(<StockReconciliationPanel data={{ ...base, ...data }} />);
}

describe("StockReconciliationPanel", () => {
  it("shows a figure for each of the two pairs", () => {
    renderPanel({
      quant_move_drift_count: 7,
      quant_move_drift_total: "12.000",
      layer_quant_drift_count: 1,
      layer_quant_drift_total: "4.000",
    });

    const rows = screen.getAllByRole("row");
    // One header row plus one row per pair.
    expect(rows).toHaveLength(3);
    expect(screen.getByText("12")).toBeInTheDocument();
    expect(screen.getByText("4")).toBeInTheDocument();
  });

  it("writes a fractional total with the reader's decimal mark", async () => {
    // 12.5 printed as "12.500" — in Polish a dot groups thousands.
    await withLanguage("pl", () => {
      renderPanel({
        quant_move_drift_count: 2,
        quant_move_drift_total: "12.500",
        previous: {
          measured_at: "2026-09-20T12:00:00+00:00",
          quant_move_drift_count: 1,
          quant_move_drift_total: "7.250",
          layer_quant_drift_count: 0,
          layer_quant_drift_total: "0.000",
        },
      });

      expect(screen.getByText("12,5")).toBeInTheDocument();
      expect(screen.getByTestId("previous-quantMove")).toHaveTextContent(
        "7,25",
      );
      expect(screen.queryByText("12.500")).not.toBeInTheDocument();
    });
  });

  it("says how much was read to reach the figures", () => {
    renderPanel({ items_scanned: 11 });
    expect(screen.getByText(/11 product records/)).toBeInTheDocument();
  });

  it("prints a dash for a pair the server did not measure", () => {
    // A read taken before the pair joined the report carries null, and a
    // null is not a zero: nothing was compared.
    renderPanel({
      quant_move_drift_count: null,
      quant_move_drift_total: null,
    });

    const ledgerRow = screen
      .getAllByRole("row")
      .find((row) => within(row).queryByText(/movement ledger/));
    expect(ledgerRow).toBeDefined();
    expect(within(ledgerRow!).getAllByText("—")).toHaveLength(2);
  });

  it("names the pair whose standing gap is by design", () => {
    renderPanel();
    expect(screen.getAllByText(/by design/)).toHaveLength(2);
  });

  it("puts the watched pairs beside their previous measurement", () => {
    renderPanel({
      quant_move_drift_count: 7,
      quant_move_drift_total: "12.000",
      layer_quant_drift_count: 1,
      layer_quant_drift_total: "4.000",
      previous: {
        measured_at: "2026-09-20T12:00:00+00:00",
        quant_move_drift_count: 7,
        quant_move_drift_total: "12.000",
        layer_quant_drift_count: 1,
        layer_quant_drift_total: "4.000",
      },
    });

    const ledger = screen.getByTestId("previous-quantMove");
    expect(ledger).toHaveTextContent(/Previous measurement/);
    expect(ledger).toHaveTextContent("7");
    expect(ledger).toHaveTextContent("12");
    expect(ledger).not.toHaveTextContent("12.000");
    expect(within(ledger).getByText("standing")).toBeInTheDocument();

    const layers = screen.getByTestId("previous-layerQuant");
    expect(layers).toHaveTextContent("4");
    expect(layers).not.toHaveTextContent("4.000");
    expect(within(layers).getByText("standing")).toBeInTheDocument();

    // The timestamp the server sent is for the machine; the reader gets the
    // rendered date, not the ISO literal.
    expect(ledger).not.toHaveTextContent("2026-09-20T12:00:00");
  });

  it("names the watched figure that grew since the previous pass", () => {
    renderPanel({
      quant_move_drift_count: 7,
      quant_move_drift_total: "15.000",
      layer_quant_drift_count: 1,
      layer_quant_drift_total: "4.000",
      previous: {
        measured_at: "2026-09-20T06:00:00+00:00",
        quant_move_drift_count: 7,
        quant_move_drift_total: "12.000",
        layer_quant_drift_count: 1,
        layer_quant_drift_total: "4.000",
      },
    });

    const ledger = screen.getByTestId("previous-quantMove");
    expect(within(ledger).getByText("grew")).toBeInTheDocument();
    // The pair beside it stood — the badge is per pair, not per table.
    const layers = screen.getByTestId("previous-layerQuant");
    expect(within(layers).getByText("standing")).toBeInTheDocument();
  });

  it("says when there is no previous measurement to compare against", () => {
    renderPanel();

    expect(screen.getByTestId("previous-quantMove-none")).toHaveTextContent(
      /Nothing to compare these figures with yet/,
    );
    expect(screen.getByTestId("previous-layerQuant-none")).toHaveTextContent(
      /Nothing to compare these figures with yet/,
    );
  });

  it("reads a zero with no previous pass as a measurement, not as nothing measured", () => {
    // The figures are counted when the screen asks; only the comparison
    // waits for the scheduled job. "No previous measurement yet" beside
    // a 0 read as "nobody has checked", which made the zero look like a
    // placeholder rather than the agreement it is.
    renderPanel();

    expect(
      screen.getByText(/Measured on opening this screen/),
    ).toBeInTheDocument();
    expect(
      screen.queryByText(/No previous measurement/),
    ).not.toBeInTheDocument();
    const ledger = screen
      .getByText("The shelf vs the movement ledger")
      .closest("tr") as HTMLElement;
    expect(within(ledger).getAllByText("0")).toHaveLength(2);
  });

  it("keeps nothing of the pairs that ended with the quant table", () => {
    // The records against the table, and the table against the records'
    // view: their row, the verdict badge that was theirs alone and their
    // per-location breakdown went with the table.
    renderPanel();

    expect(
      screen.queryByText(/Product records vs the shelf/),
    ).not.toBeInTheDocument();
    expect(screen.queryByText("In agreement")).not.toBeInTheDocument();
    expect(screen.queryByText("Drift found")).not.toBeInTheDocument();
    expect(
      screen.queryByText(/Where the records and the shelf/),
    ).not.toBeInTheDocument();
  });
});
