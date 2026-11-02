import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, it, expect, vi } from "vitest";
import { AssetCardRow } from "../components/AssetCardRow";
import type { EquipmentAssetItem } from "../api/equipment_assets";

function makeItem(
  overrides: Partial<EquipmentAssetItem> = {},
): EquipmentAssetItem {
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
    location_name: null,
    holder_name: null,
    holder_kind: null,
    ...overrides,
  } as EquipmentAssetItem;
}

const renderRow = (
  item: EquipmentAssetItem,
  {
    isSelected = false,
    onToggleSelect = vi.fn(),
  }: {
    isSelected?: boolean;
    onToggleSelect?: (id: string) => void;
  } = {},
) =>
  render(
    <MemoryRouter>
      <AssetCardRow
        item={item}
        isSelected={isSelected}
        onToggleSelect={onToggleSelect}
        image={
          item.image_url ? { url: item.image_url, fromModel: false } : null
        }
        locationName={item.location_name ?? null}
      />
    </MemoryRouter>,
  );

describe("AssetCardRow — thumbnail", () => {
  it("renders the item image when image_url is present", () => {
    renderRow(makeItem({ image_url: "/uploads/items/i1/cover.png" }));
    const img = screen.getByRole("img", { name: "ThinkPad X1" });
    expect(img).toHaveAttribute("src", "/uploads/items/i1/cover.png");
  });

  it("renders the fallback Monitor icon when there is no image", () => {
    const { container } = renderRow(makeItem({ image_url: null }));
    // No <img> should be present.
    expect(container.querySelector("img")).toBeNull();
    // The Monitor icon (svg) is rendered as the fallback.
    expect(container.querySelector("svg")).toBeTruthy();
  });
});

describe("AssetCardRow — subtitle", () => {
  it("renders the nested category name from item.category", () => {
    renderRow(
      makeItem({
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
      }),
    );
    expect(screen.getByText("Laptop")).toBeInTheDocument();
  });
});

describe("AssetCardRow — category icon", () => {
  const category = (icon: string | null) => ({
    id: "cat-1",
    name: "Laptop",
    code: "LAPTOP",
    context_tag: "equipment",
    icon,
    sort_order: 1,
    meta_data: null,
    is_active: true,
    is_module_owned: false,
    field_definitions: [],
  });

  it("renders the category icon instead of a hardcoded Monitor", () => {
    const { container } = renderRow(
      makeItem({
        image_url: null,
        category_id: "cat-1",
        category: category("laptop"),
      }),
    );
    expect(container.querySelector(".lucide-laptop")).toBeTruthy();
    expect(container.querySelector(".lucide-monitor")).toBeNull();
  });

  it("falls back to Monitor when the category has no icon", () => {
    const { container } = renderRow(
      makeItem({
        image_url: null,
        category_id: "cat-1",
        category: category(null),
      }),
    );
    expect(container.querySelector(".lucide-monitor")).toBeTruthy();
  });
});

describe("AssetCardRow — location and holder", () => {
  it("shows where the asset is and who holds it", () => {
    renderRow(
      makeItem({
        location_name: "Server Room",
        holder_name: "Alice Nowak",
        holder_kind: "person",
      }),
    );
    expect(screen.getByText("Server Room")).toBeInTheDocument();
    expect(screen.getByText("Held by Alice Nowak")).toBeInTheDocument();
  });

  it("names a placed asset's place once, as its location", () => {
    renderRow(
      makeItem({
        location_name: "Server Rack A",
        holder_name: "Server Rack A",
        holder_kind: "location",
      }),
    );
    expect(screen.getAllByText(/Server Rack A/)).toHaveLength(1);
    expect(screen.queryByText(/Held by/)).not.toBeInTheDocument();
  });

  it("renders no subtitle line when both fields are empty", () => {
    renderRow(makeItem());
    expect(screen.queryByText(/Held by/)).not.toBeInTheDocument();
  });
});

/**
 * Below `md:` the asset list renders these cards and nothing else, and the
 * card navigated from a `<Card onClick>` with the name in a plain `<span>`:
 * no role, no focus, no href, so on a phone no asset could be opened with a
 * keyboard at all — Tab jumped from the selection checkbox straight out of
 * the card. The name is a real link stretched over the card now
 * (UI_GUIDELINES §2.3a), the same shape the table already had.
 */
describe("AssetCardRow — keyboard path to the record", () => {
  it("offers the asset as one real link to its record", () => {
    renderRow(makeItem());

    const link = screen.getByRole("link", { name: "ThinkPad X1" });
    expect(link).toHaveAttribute("href", "/equipment/i1");
    // The card's one destination, not a duplicate beside the card body.
    expect(screen.getAllByRole("link")).toHaveLength(1);
  });

  it("reaches the link with Tab from the checkbox", async () => {
    const user = userEvent.setup();
    renderRow(makeItem());

    const checkbox = screen.getByRole("checkbox", { name: /select asset/i });
    checkbox.focus();
    await user.tab();

    expect(screen.getByRole("link", { name: "ThinkPad X1" })).toHaveFocus();
  });

  it("keeps the checkbox operable above the stretched link", () => {
    const onToggleSelect = vi.fn();
    renderRow(makeItem(), { isSelected: false, onToggleSelect });

    const checkbox = screen.getByRole("checkbox", { name: /select asset/i });
    // The overlay covers the whole card, so the checkbox has to sit above it
    // or a tap would open the record instead of ticking the row.
    expect(checkbox.closest(".z-10")).not.toBeNull();

    checkbox.click();
    expect(onToggleSelect).toHaveBeenCalledWith("i1");
  });
});
