import { render, screen, fireEvent } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { AssetTable, getWarrantyState } from "../components/AssetTable";
import type { EquipmentAssetItem } from "../api/equipment_assets";

function makeItem(
  overrides: Partial<EquipmentAssetItem> = {},
): EquipmentAssetItem {
  const soon = new Date();
  soon.setDate(soon.getDate() + 10);
  return {
    id: "i1",
    name: "ThinkPad X1",
    location_id: "loc-1",
    category_id: "cat-1",
    quantity: 1,
    added_date: "2024-01-01",
    created_at: "2024-01-01",
    updated_at: "2024-01-01",
    image_url: null,
    location_name: "Server Room",
    holder_name: "Alice Nowak",
    holder_kind: "person",
    metadata: {
      equipment: {
        equipment_status: "AVAILABLE",
        serial_number: "SN-001",
        warranty_until: soon.toISOString().slice(0, 10),
      },
    },
    ...overrides,
  } as EquipmentAssetItem;
}

const renderTable = (
  items: EquipmentAssetItem[],
  props: Partial<Parameters<typeof AssetTable>[0]> = {},
) =>
  render(
    <MemoryRouter>
      <AssetTable
        items={items}
        selectedIds={new Set()}
        onToggleSelect={vi.fn()}
        onToggleSelectAll={vi.fn()}
        sort="created_at"
        sortDir="desc"
        onSortChange={vi.fn()}
        locationLabel={(_id, rawName) => rawName ?? null}
        {...props}
      />
    </MemoryRouter>,
  );

describe("AssetTable", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it("renders the answer columns: location, assignee, serial, warranty, status", () => {
    renderTable([makeItem()]);
    expect(screen.getByText("ThinkPad X1")).toBeInTheDocument();
    expect(screen.getByText("Server Room")).toBeInTheDocument();
    expect(screen.getByText("Alice Nowak")).toBeInTheDocument();
    expect(screen.getByText("SN-001")).toBeInTheDocument();
    expect(screen.getByText(/Expiring/)).toBeInTheDocument();
    expect(screen.getByText("Available")).toBeInTheDocument();
  });

  it("calls onSortChange with the key when a sortable header is clicked", () => {
    const onSortChange = vi.fn();
    renderTable([makeItem()], { onSortChange });
    fireEvent.click(screen.getByRole("button", { name: "Sort by Name" }));
    expect(onSortChange).toHaveBeenCalledWith("name");
    fireEvent.click(screen.getByRole("button", { name: "Sort by Warranty" }));
    expect(onSortChange).toHaveBeenCalledWith("warranty_until");
  });

  it("hides a column when unticked in the column picker", () => {
    renderTable([makeItem()]);
    // "Serial / Tag" column is present by default.
    expect(screen.getByText("SN-001")).toBeInTheDocument();
    fireEvent.click(screen.getByText("Columns"));
    fireEvent.click(screen.getByLabelText("Serial / Tag"));
    expect(screen.queryByText("SN-001")).not.toBeInTheDocument();
  });

  it("renders an em-dash for assets without a location or assignee", () => {
    renderTable([makeItem({ location_name: null, holder_name: null })]);
    expect(screen.getAllByText("—").length).toBeGreaterThanOrEqual(2);
  });

  // A place used to sit in the Assigned-to column while the Location column
  // still named where the asset had stood before: two answers to "where".
  // The asset is moved into the place now, so the place is its location and
  // the holder column names people only — the phone card's words.
  it("names a placed asset's place once, as its location", () => {
    renderTable([
      makeItem({
        location_name: "Server Rack A",
        holder_name: "Server Rack A",
        holder_kind: "location",
      }),
    ]);
    expect(screen.getAllByText("Server Rack A")).toHaveLength(1);
    expect(screen.getByRole("columnheader", { name: /Held by/ })).toBeVisible();
  });

  // An asset created through the generic item API carries no equipment
  // namespace, so no status was ever recorded for it — the reader used to
  // see it wearing AVAILABLE, a fact nobody wrote down.
  it("calls an asset whose status was never set unknown, not available", () => {
    renderTable([makeItem({ metadata: null, name: "No Status" })]);
    expect(screen.getByText("No Status")).toBeInTheDocument();
    expect(screen.getByText(/unknown/i)).toBeInTheDocument();
    expect(screen.queryByText("Available")).not.toBeInTheDocument();
  });
});

/**
 * the row was mouse-only: `<tr onClick>` with the name as a plain span,
 * so the one focusable thing in the row was the selection checkbox and a
 * keyboard reader had no way to open an asset. The name is a real link
 * now — the same shape the inventory list leads to a record with — so
 * Enter, the middle button and "open in a new tab" all reach the card.
 */
describe("AssetTable — the row opens through a link", () => {
  const renderRouted = (items: EquipmentAssetItem[]) =>
    render(
      <MemoryRouter initialEntries={["/equipment/assets"]}>
        <Routes>
          <Route
            path="/equipment/assets"
            element={
              <AssetTable
                items={items}
                selectedIds={new Set()}
                onToggleSelect={vi.fn()}
                onToggleSelectAll={vi.fn()}
                sort="created_at"
                sortDir="desc"
                onSortChange={vi.fn()}
                locationLabel={(_id, rawName) => rawName ?? null}
              />
            }
          />
          <Route path="/equipment/:id" element={<p>DETAIL RENDERED</p>} />
        </Routes>
      </MemoryRouter>,
    );

  it("gives every row one link named after its asset", () => {
    renderRouted([
      makeItem({ id: "link-1", name: "QA Monitor 001" }),
      makeItem({ id: "link-2", name: "QA Keyboard 002" }),
    ]);

    expect(screen.getAllByRole("link")).toHaveLength(2);
    expect(
      screen.getByRole("link", { name: "QA Monitor 001" }),
    ).toHaveAttribute("href", "/equipment/link-1");
  });

  it("opens the detail with Enter on the focused link", async () => {
    const user = userEvent.setup();
    renderRouted([makeItem({ id: "kb-1", name: "QA Monitor 001" })]);

    screen.getByRole("link", { name: "QA Monitor 001" }).focus();
    await user.keyboard("{Enter}");

    expect(await screen.findByText("DETAIL RENDERED")).toBeInTheDocument();
  });

  it("does not navigate when the click lands on the row, not the link", () => {
    renderRouted([makeItem({ id: "row-1", name: "QA Monitor 001" })]);

    fireEvent.click(screen.getByText("SN-001"));

    expect(screen.queryByText("DETAIL RENDERED")).not.toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "QA Monitor 001" }),
    ).toBeInTheDocument();
  });
});

/**
 * A warranty end is a day printed on the invoice, not an instant.
 * `new Date("2026-09-10")` is midnight UTC while local midnight is another
 * moment, and the offset between them leaked into the count: east of
 * Greenwich a warranty that had ended yesterday left `Math.ceil` at zero
 * days, so the badge said "expiring" on the day after it expired.
 */
describe("getWarrantyState — a warranty ends on a calendar day", () => {
  function inZone(zone: string, now: Date, body: () => void): void {
    const original = process.env.TZ;
    process.env.TZ = zone;
    vi.useFakeTimers();
    vi.setSystemTime(now);
    try {
      body();
    } finally {
      vi.useRealTimers();
      process.env.TZ = original;
    }
  }

  const warrantyUntil = (day: string) =>
    makeItem({ metadata: { equipment: { warranty_until: day } } });

  it("calls a warranty that ended yesterday expired east of UTC", () => {
    // Midday on 11 September 2026 in Warsaw: local midnight was 22:00 UTC on
    // the 10th, so UTC midnight of the 10th is 22 hours in the past.
    inZone("Europe/Warsaw", new Date(2026, 8, 11, 12, 0, 0), () => {
      expect(getWarrantyState(warrantyUntil("2026-09-10"))).toBe("expired");
    });
  });

  it("keeps the 30-day warning on calendar days", () => {
    // UTC midnight of the 11th is 22:00 on the 10th locally, so the old
    // ceil() arithmetic read a warranty due in exactly 30 days as 31 and
    // went quiet one day early.
    inZone("Europe/Warsaw", new Date(2026, 8, 11, 12, 0, 0), () => {
      expect(getWarrantyState(warrantyUntil("2026-10-11"))).toBe("expiring");
      expect(getWarrantyState(warrantyUntil("2026-10-12"))).toBe("active");
    });
  });

  it("does not call a warranty that ends today expired", () => {
    inZone("Europe/Warsaw", new Date(2026, 8, 11, 12, 0, 0), () => {
      expect(getWarrantyState(warrantyUntil("2026-09-11"))).toBe("expiring");
    });
  });
});

describe("getWarrantyState", () => {
  const daysFromNow = (days: number) => {
    const d = new Date();
    d.setDate(d.getDate() + days);
    return d.toISOString().slice(0, 10);
  };

  it("classifies expired, expiring, active and missing warranties", () => {
    expect(
      getWarrantyState(
        makeItem({
          metadata: { equipment: { warranty_until: daysFromNow(-10) } },
        }),
      ),
    ).toBe("expired");
    expect(
      getWarrantyState(
        makeItem({
          metadata: { equipment: { warranty_until: daysFromNow(10) } },
        }),
      ),
    ).toBe("expiring");
    expect(
      getWarrantyState(
        makeItem({
          metadata: { equipment: { warranty_until: daysFromNow(120) } },
        }),
      ),
    ).toBe("active");
    expect(getWarrantyState(makeItem({ metadata: { equipment: {} } }))).toBe(
      "none",
    );
  });
});
