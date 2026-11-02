import { describe, it, expect } from "vitest";
import { http, HttpResponse } from "msw";
import { server } from "@/test/mocks/server";
import type { Category } from "@/types";
import type { EquipmentAssetItem } from "@/modules/equipment/api/equipment_assets";
import {
  bucketFleet,
  fetchWholeFleet,
} from "@/modules/equipment/hooks/useFleetComposition";

function category(id: string, name = id): Category {
  return { id, name, code: null, icon: null } as Category;
}

function asset(
  id: string,
  opts: {
    category?: Category | null;
    status?: string;
    holder?: string | null;
  } = {},
): EquipmentAssetItem {
  const cat = opts.category === undefined ? category("laptops") : opts.category;
  return {
    id,
    name: id,
    category_id: cat?.id ?? null,
    category: cat ?? undefined,
    metadata: opts.status
      ? { equipment: { equipment_status: opts.status } }
      : null,
    holder_name: opts.holder ?? null,
    holder_kind: opts.holder ? "person" : null,
    location_name: null,
  } as EquipmentAssetItem;
}

const none = new Set<string>();

describe("bucketFleet", () => {
  it("files every asset under its category and counts the parts", () => {
    const laptops = category("laptops", "Laptops");
    const phones = category("phones", "Phones");
    const rows = bucketFleet(
      [
        asset("a", { category: laptops, holder: "K. Nowak" }),
        asset("b", { category: laptops }),
        asset("c", { category: laptops, status: "MAINTENANCE" }),
        asset("d", { category: phones, holder: "M. Zielińska" }),
      ],
      none,
    );

    expect(rows.map((r) => [r.key, r.count])).toEqual([
      ["laptops", 3],
      ["phones", 1],
    ]);
    expect(rows[0].segments).toEqual({ warn: 0, issued: 1, service: 1, ok: 1 });
    expect(rows[1].segments).toEqual({ warn: 0, issued: 1, service: 0, ok: 0 });
    expect(rows[0].category?.name).toBe("Laptops");
  });

  it("counts an asset with an open assignment as issued, whatever its status says", () => {
    // The backend's rule for the tiles: a checked-out asset is counted once,
    // as issued, even when a maintenance entry set its status meanwhile.
    const rows = bucketFleet(
      [asset("a", { status: "MAINTENANCE", holder: "K. Nowak" })],
      none,
    );
    expect(rows[0].segments).toEqual({ warn: 0, issued: 1, service: 0, ok: 0 });
  });

  it("marks an ending warranty only on what stands on the shelf, so 'checked out' counts every held asset", () => {
    const rows = bucketFleet(
      [
        asset("a", { holder: "K. Nowak" }),
        asset("b", { status: "MAINTENANCE" }),
        asset("c"),
        asset("d"),
      ],
      new Set(["a", "b", "c"]),
    );
    expect(rows[0].segments).toEqual({ warn: 1, issued: 1, service: 1, ok: 1 });
  });

  it("leaves a retired asset out of the fleet unless somebody still holds it", () => {
    const rows = bucketFleet(
      [
        asset("gone", { status: "RETIRED" }),
        asset("held", { status: "RETIRED", holder: "K. Nowak" }),
        asset("kept"),
      ],
      none,
    );
    expect(rows[0].count).toBe(2);
    expect(rows[0].segments).toEqual({ warn: 0, issued: 1, service: 0, ok: 1 });
  });

  it("gives assets filed under no category a row of their own, last", () => {
    const rows = bucketFleet(
      [
        asset("x", { category: null }),
        asset("y", { category: null }),
        asset("z", { category: category("monitors") }),
      ],
      none,
    );
    expect(rows.map((r) => [r.key, r.count, r.category])).toEqual([
      ["monitors", 1, expect.objectContaining({ id: "monitors" })],
      ["none", 2, null],
    ]);
  });

  it("orders equal counts by name, so the card does not reshuffle", () => {
    const rows = bucketFleet(
      [
        asset("a", { category: category("p", "Phones") }),
        asset("b", { category: category("m", "Monitors") }),
      ],
      none,
    );
    expect(rows.map((r) => r.key)).toEqual(["m", "p"]);
  });
});

describe("fetchWholeFleet", () => {
  it("walks the pages until the server's total, so a fleet past one page is counted whole", async () => {
    const all = Array.from({ length: 450 }, (_, i) => asset(`a${i}`));
    const offsets: number[] = [];
    server.use(
      http.get("/api/v1/equipment/assets", ({ request }) => {
        const params = new URL(request.url).searchParams;
        const limit = Number(params.get("limit"));
        const offset = Number(params.get("offset"));
        offsets.push(offset);
        return HttpResponse.json({
          items: all.slice(offset, offset + limit),
          total: all.length,
          limit,
          offset,
          has_more: offset + limit < all.length,
        });
      }),
    );

    const fleet = await fetchWholeFleet();

    expect(fleet).toHaveLength(450);
    expect(offsets).toEqual([0, 200, 400]);
  });

  it("stops on a short page, and does not count an asset twice", async () => {
    // A page boundary moved by an asset added between two requests repeats
    // the row that slid across it.
    let calls = 0;
    server.use(
      http.get("/api/v1/equipment/assets", () => {
        calls += 1;
        return HttpResponse.json({
          items: [asset("a"), asset("a"), asset("b")],
          total: 3,
        });
      }),
    );

    const fleet = await fetchWholeFleet();

    expect(calls).toBe(1);
    expect(fleet.map((a) => a.id)).toEqual(["a", "b"]);
  });
});
