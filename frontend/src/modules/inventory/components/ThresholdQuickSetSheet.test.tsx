import { render, screen } from "@/test/utils";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi } from "vitest";
import ThresholdQuickSetSheet from "./ThresholdQuickSetSheet";
import type { Item } from "@/types";

const mutate = vi.fn();

vi.mock("@/modules/inventory/hooks/useItemMutations", () => ({
  useUpdateItem: () => ({ mutate, isPending: false }),
}));

const item: Item = {
  is_deleted: false,
  id: "item-1",
  location_id: "storage-1",
  category_id: null,
  name: "Olive oil",
  brand: null,
  description: null,
  weight: null,
  quantity: "7",
  added_date: "2026-01-01",
  expiry_date: null,
  freeze_date: null,
  shelf_location: null,
  image_url: null,
  metadata: null,
  created_at: "2026-01-01T00:00:00",
  updated_at: "2026-01-01T00:00:00",
};

describe("ThresholdQuickSetSheet", () => {
  it("starts empty for an item that has no threshold yet", () => {
    render(<ThresholdQuickSetSheet item={item} onClose={() => {}} />);

    expect(screen.getByTestId("threshold-input")).toHaveValue(null);
  });

  it("starts from the threshold the item already carries", () => {
    render(
      <ThresholdQuickSetSheet
        item={{ ...item, min_quantity: 3 }}
        onClose={() => {}}
      />,
    );

    expect(screen.getByTestId("threshold-input")).toHaveValue(3);
  });

  it("cannot be saved until a number is entered", async () => {
    const user = userEvent.setup();
    render(<ThresholdQuickSetSheet item={item} onClose={() => {}} />);

    const save = screen.getByRole("button", { name: /set alert|save/i });
    expect(save).toBeDisabled();

    await user.type(screen.getByTestId("threshold-input"), "2");
    expect(save).toBeEnabled();
  });

  it("keeps the shortcut that fills in the quantity on the shelf", async () => {
    const user = userEvent.setup();
    render(<ThresholdQuickSetSheet item={item} onClose={() => {}} />);

    await user.click(screen.getByRole("button", { name: /current quantity/i }));

    expect(screen.getByTestId("threshold-input")).toHaveValue(7);
  });

  it("accepts a fractional threshold", async () => {
    const user = userEvent.setup();
    render(<ThresholdQuickSetSheet item={item} onClose={() => {}} />);

    await user.type(screen.getByTestId("threshold-input"), "0.5");
    await user.click(screen.getByRole("button", { name: /set alert|save/i }));

    expect(mutate).toHaveBeenCalledWith(
      { id: "item-1", data: { min_quantity: 0.5 } },
      expect.anything(),
    );
  });
});
