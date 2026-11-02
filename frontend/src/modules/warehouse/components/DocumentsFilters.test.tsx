import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { scanWithHardwareScanner } from "@/test/scanner";
import { DocumentsFilters } from "./DocumentsFilters";

const LABELS: Record<string, string> = {
  "warehouse:filters.type": "Type",
  "warehouse:filters.status": "Status",
  "warehouse:types.ALL": "All",
  "types.ALL": "All",
  // the tabs name the type (`types`), which in Polish carries the code too
  "types.CORRECTION": "Correction",
};

function renderFilters(setSearch = vi.fn()) {
  return render(
    <DocumentsFilters
      search=""
      setSearch={setSearch}
      typeFilter="ALL"
      setTypeFilter={vi.fn()}
      statusFilter="ALL"
      setStatusFilter={vi.fn()}
      discrepancyFilter="ALL"
      setDiscrepancyFilter={vi.fn()}
      dateFrom=""
      setDateFrom={vi.fn()}
      dateTo=""
      setDateTo={vi.fn()}
      sortBy="document_date"
      sortOrder="desc"
      setSortBy={vi.fn()}
      setSortOrder={vi.fn()}
      t={(key: string) => LABELS[key] ?? key}
    />,
  );
}

describe("DocumentsFilters", () => {
  it("searches for a code a hardware scanner reads, with no field focused", () => {
    const setSearch = vi.fn();
    renderFilters(setSearch);
    expect(
      screen.getByText("A barcode scanner can be used on this screen"),
    ).toBeInTheDocument();

    scanWithHardwareScanner("OUT/2026/014", document.body);

    expect(setSearch).toHaveBeenCalledTimes(1);
    expect(setSearch).toHaveBeenCalledWith("OUT/2026/014");
  });

  it("names the phone-only type select", () => {
    renderFilters();
    // It had no label and no aria-label, so assistive technology fell back to
    // concatenating the options ("AllReceiptDeliveryTransfer…").
    // moved it behind the phone "Filters" toggle, so open that first.
    fireEvent.click(screen.getByRole("button", { name: /filters\.title/i }));
    expect(screen.getByRole("combobox", { name: "Type" })).toBeInTheDocument();
  });

  it("says which row filters by type and which by status", () => {
    renderFilters();
    // Both rows open with "All"; without the captions they read as one filter.
    expect(screen.getAllByText("Type").length).toBeGreaterThan(0);
    expect(
      screen.getAllByRole("group", { name: "Status" }).length,
    ).toBeGreaterThan(0);
  });

  it("spells out the correction type instead of abbreviating it", () => {
    renderFilters();
    // "CORR" was the only abbreviation among full names.
    expect(screen.getAllByText("Correction").length).toBeGreaterThan(0);
  });
});
