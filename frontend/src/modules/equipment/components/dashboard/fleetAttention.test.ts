import { describe, it, expect } from "vitest";
import i18n from "@/test/mocks/i18n";
import type { EquipmentAssetItem } from "@/modules/equipment/api/equipment_assets";
import type { OverdueAssignmentItem } from "@/modules/equipment/api/equipment_assignments";
import type { WarrantyAlert } from "@/modules/equipment/api/equipment_dashboard";
import { toFleetAttention } from "@/modules/equipment/components/dashboard/fleetAttention";

const t = i18n.getFixedT("en", "equipment");

function overdue(
  itemId: string,
  days: number,
  extra: Partial<OverdueAssignmentItem> = {},
): OverdueAssignmentItem {
  return {
    assignment_id: `asg-${itemId}`,
    item_id: itemId,
    item_name: "MacBook Pro 14",
    item_barcode: null,
    item_serial: null,
    item_asset_tag: null,
    holder_name: "K. Nowak",
    holder_kind: "person",
    assigned_to_email: null,
    checked_out_at: "2026-09-01T08:00:00Z",
    expected_return_at: "2026-09-19T08:00:00Z",
    days_overdue: days,
    ...extra,
  };
}

function warranty(
  itemId: string,
  days: number,
  extra: Partial<WarrantyAlert> = {},
): WarrantyAlert {
  return {
    item_id: itemId,
    item_name: "Dell U2723QE",
    warranty_until: "2026-10-04",
    days_remaining: days,
    serial_number: null,
    assigned_to: null,
    category_code: "laptop",
    ...extra,
  };
}

function inService(id: string, location: string | null): EquipmentAssetItem {
  return {
    id,
    name: "HP LaserJet M404",
    serial_number: null,
    metadata: { equipment: { equipment_status: "MAINTENANCE" } },
    location_name: location,
    holder_name: null,
    holder_kind: null,
  } as unknown as EquipmentAssetItem;
}

const empty = {
  overdue: [],
  warrantyEnding: [],
  warrantyExpired: [],
  inService: [],
};

describe("toFleetAttention", () => {
  it("says why each asset is here and where it is, leading to its card", () => {
    const rows = toFleetAttention(
      {
        overdue: [overdue("mac", 3)],
        warrantyEnding: [warranty("dell", 12, { assigned_to: "M. Zielińska" })],
        warrantyExpired: [],
        inService: [inService("hp", "External service")],
      },
      t,
    );

    expect(rows).toEqual([
      expect.objectContaining({
        severity: "expired",
        title: "MacBook Pro 14",
        reason: "return overdue by 3 days",
        where: "K. Nowak",
        href: "/equipment/mac",
      }),
      expect.objectContaining({
        severity: "expiring",
        reason: "warranty ends in 12 days",
        where: "M. Zielińska",
        href: "/equipment/dell",
      }),
      expect.objectContaining({
        severity: "low",
        reason: "in maintenance",
        where: "External service",
        href: "/equipment/hp",
      }),
    ]);
  });

  it("names the place a deployed, overdue asset stands in", () => {
    const rows = toFleetAttention(
      {
        ...empty,
        overdue: [
          overdue("mac", 3, {
            holder_name: "Server Rack A",
            holder_kind: "location",
          }),
        ],
      },
      t,
    );
    expect(rows[0].where).toBe("Server Rack A");
  });

  it("names the unit beside the model, so six of one model are six rows a reader can tell apart", () => {
    const rows = toFleetAttention(
      {
        ...empty,
        overdue: [
          overdue("a", 2, { item_name: "OptiPlex 7010", item_serial: "SN-1" }),
        ],
        warrantyEnding: [
          warranty("b", 5, {
            item_name: "OptiPlex 7010",
            serial_number: "SN-2",
          }),
        ],
      },
      t,
    );
    expect(rows.map((r) => r.title)).toEqual([
      "OptiPlex 7010 · SN-1",
      "OptiPlex 7010 · SN-2",
    ]);
  });

  it("reads a warranty that ends today as today, and one day in the singular", () => {
    const rows = toFleetAttention(
      {
        ...empty,
        warrantyEnding: [warranty("a", 0), warranty("b", 1)],
      },
      t,
    );
    expect(rows.map((r) => r.reason)).toEqual([
      "warranty ends today",
      "warranty ends in 1 day",
    ]);
  });

  it("says a return is overdue without counting zero days", () => {
    const rows = toFleetAttention({ ...empty, overdue: [overdue("a", 0)] }, t);
    expect(rows[0].reason).toBe("return overdue");
  });

  it("lists an expired warranty as a note, with the date it ended", () => {
    const rows = toFleetAttention(
      {
        ...empty,
        warrantyExpired: [
          warranty("old", -30, { warranty_until: "2026-08-23" }),
        ],
      },
      t,
    );
    expect(rows[0]).toEqual(
      expect.objectContaining({ severity: "info", href: "/equipment/old" }),
    );
    expect(rows[0].reason).toMatch(/^warranty ended /);
  });

  it("counts an asset once, under its most urgent reason", () => {
    const rows = toFleetAttention(
      {
        overdue: [overdue("a", 3)],
        warrantyEnding: [warranty("a", 4)],
        warrantyExpired: [warranty("b", -3)],
        inService: [inService("b", null)],
      },
      t,
    );
    expect(rows.map((r) => [r.href, r.severity])).toEqual([
      ["/equipment/a", "expired"],
      ["/equipment/b", "low"],
    ]);
  });
});
