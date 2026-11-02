import { describe, expect, it } from "vitest";
import { render, screen } from "@/test/utils";
import { server } from "@/test/mocks/server";
import { http, HttpResponse } from "msw";
import { InfoTab } from "@/modules/equipment/components/AssetInfoTab";
import type { Item } from "@/types";
import { onePage } from "@/test/mocks/page";

/**
 * Regression guard.
 *
 * - InfoRow used to return null for empty values, leaving bare section
 *   headers in Basic Info / Identification when the item has no
 *   meta_data.equipment.* values.
 * - getEquipmentMeta ignored top-level Item.serial_number / Item.brand,
 *   even though the backend falls back to them (dashboard_service.py).
 */

const makeItem = (overrides: Partial<Item> = {}): Item => ({
  id: "item-1",
  location_id: "loc-1",
  category_id: null,
  name: "Asset 1",
  brand: null,
  description: null,
  weight: null,
  quantity: "1",
  added_date: "2026-01-01",
  expiry_date: null,
  freeze_date: null,
  shelf_location: null,
  image_url: null,
  metadata: null,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
  is_deleted: false,
  ...overrides,
});

describe("InfoTab — empty equipment metadata", () => {
  it("renders section rows with an em-dash instead of dropping them", () => {
    render(<InfoTab item={makeItem()} />);
    expect(screen.getByText("Basic Info")).toBeInTheDocument();
    expect(screen.getByText("Identification")).toBeInTheDocument();
    expect(screen.getByText("Manufacturer")).toBeInTheDocument();
    expect(screen.getByText("Serial Number")).toBeInTheDocument();
    expect(screen.getAllByText("—").length).toBeGreaterThanOrEqual(3);
  });

  it("reads Item.serial_number and falls back to Item.brand", () => {
    render(
      <InfoTab
        item={makeItem({ serial_number: "SN-TOP", brand: "Acme Corp" })}
      />,
    );
    expect(screen.getByText("SN-TOP")).toBeInTheDocument();
    expect(screen.getByText("Acme Corp")).toBeInTheDocument();
  });

  it("reads the serial from the column and the rest from the namespace", () => {
    // The serial number lives in the core column — one home, so the core
    // search can reach it. Everything else the module owns still comes
    // from its namespace, which wins over the core Item fields.
    render(
      <InfoTab
        item={makeItem({
          serial_number: "SN-TOP",
          brand: "Acme Corp",
          metadata: {
            equipment: {
              serial_number: "SN-META",
              manufacturer: "Meta Brand",
            },
          },
        })}
      />,
    );
    expect(screen.getByText("SN-TOP")).toBeInTheDocument();
    expect(screen.getByText("Meta Brand")).toBeInTheDocument();
    expect(screen.queryByText("SN-META")).not.toBeInTheDocument();
    expect(screen.queryByText("Acme Corp")).not.toBeInTheDocument();
  });

  it("renders the nested category name instead of an em-dash", () => {
    render(
      <InfoTab
        item={makeItem({
          category_id: "cat-1",
          category: {
            is_active: true,
            field_definitions: [],
            id: "cat-1",
            name: "Laptop",
            code: "LAPTOP",
            context_tag: "equipment",
            icon: "laptop",
            sort_order: 1,
            meta_data: null,
          },
        })}
      />,
    );
    // The API returns the category as a nested object; the flat
    // category_name fallback is absent, so the row must read category.name.
    expect(screen.getByText("Laptop")).toBeInTheDocument();
  });

  it("links the location to the asset list, filtered", async () => {
    server.use(
      http.get("/api/v1/locations", () =>
        HttpResponse.json(
          onePage([
            {
              id: "loc-1",
              user_id: "u1",
              location_type_id: null,
              parent_id: null,
              name: "Server Room",
              description: null,
              location_details: null,
              settings: null,
              created_at: "2024-01-01T00:00:00Z",
              context_schema: [],
              behavior_mode: "NONE",
              field_definitions: [],
              context_tag: "equipment",
            },
          ]),
        ),
      ),
    );
    render(<InfoTab item={makeItem({ location_id: "loc-1" })} />);
    const link = await screen.findByRole("link", { name: "Server Room" });
    expect(link).toHaveAttribute("href", "/equipment/assets?location=loc-1");
  });
});

describe("InfoTab — the category list did not arrive", () => {
  it("says so where the category's fields would be, instead of dropping them silently", async () => {
    server.use(
      http.get("/api/v1/categories", () =>
        HttpResponse.json({ detail: "boom" }, { status: 500 }),
      ),
    );
    render(<InfoTab item={makeItem({ category_id: "cat-1" })} />);

    expect(
      await screen.findByRole("button", { name: /try again/i }),
    ).toBeInTheDocument();
  });
});
