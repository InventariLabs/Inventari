import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { tFor } from "@/test/mocks/i18n";
import type { CategoryDTO } from "@/types";
import { StorageItemsFilters } from "./StorageItemsFilters";

const categories = [
  { id: "c-1", code: "TOOLS", name: "Tools" },
] as unknown as CategoryDTO[];

/** The chosen chip is told by name and state, not by its fill alone. */
describe("StorageItemsFilters — the chosen chip", () => {
  it.each(["ALL", "c-1", "NONE"])("marks only %s as pressed", (selected) => {
    render(
      <StorageItemsFilters
        t={tFor("items")}
        usedCategoriesData={categories}
        hasUncategorized
        selectedCategoryId={selected}
        onSelectCategory={vi.fn()}
        itemCount={2}
      />,
    );

    const pressed = screen.getAllByRole("button").map((button) => ({
      pressed: button.getAttribute("aria-pressed"),
    }));
    const order = ["ALL", "c-1", "NONE"];
    expect(pressed).toEqual(
      order.map((id) => ({ pressed: String(id === selected) })),
    );
  });
});
