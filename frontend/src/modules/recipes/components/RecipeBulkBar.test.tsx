import { describe, it, expect, vi } from "vitest";
import { act, render, screen, fireEvent } from "@testing-library/react";
import { RecipeBulkBar } from "./RecipeBulkBar";
import en from "@/modules/recipes/i18n/en.json";
import common from "@/i18n/locales/en/common.json";
import type { TFunction } from "i18next";
import type { RecipeCollection } from "@/modules/recipes/types/core";

const t = ((key: string) => {
  const ns = key.startsWith("common:") ? common : en;
  const path = key.replace(/^(common|recipes):/, "").split(".");
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  let value: any = ns;
  for (const part of path) value = value?.[part];
  return typeof value === "string" ? value : key;
}) as unknown as TFunction;

const collection = (id: string, name: string): RecipeCollection => ({
  id,
  name,
  icon: null,
  parent_id: null,
  recipe_count: 0,
  children: [],
});

const baseProps = {
  open: true,
  selectedCount: 2,
  allSelected: false,
  isBusy: false,
  collections: [collection("c1", "Dinners")],
  onSelectAll: vi.fn(),
  onTag: vi.fn(),
  onDelete: vi.fn(),
  onAddToCollection: vi.fn().mockResolvedValue(undefined),
  onClear: vi.fn(),
  t,
};

describe("RecipeBulkBar — select all", () => {
  it("offers Select all and calls onSelectAll", () => {
    render(<RecipeBulkBar {...baseProps} />);
    const button = screen.getByRole("button", { name: "Select all" });
    fireEvent.click(button);
    expect(baseProps.onSelectAll).toHaveBeenCalledTimes(1);
  });

  it("switches the label to Deselect all when all are selected", () => {
    render(<RecipeBulkBar {...baseProps} allSelected />);
    expect(
      screen.getByRole("button", { name: "Deselect all" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Select all" }),
    ).not.toBeInTheDocument();
  });
});

describe("RecipeBulkBar — add to collection", () => {
  it("adds the selected recipes to the picked collection", async () => {
    render(<RecipeBulkBar {...baseProps} />);
    fireEvent.click(screen.getByRole("button", { name: "Add to collection" }));
    fireEvent.click(screen.getByText("Dinners"));
    fireEvent.click(screen.getByRole("button", { name: "Add" }));
    expect(baseProps.onAddToCollection).toHaveBeenCalledWith("c1");
    // The menu's close transition settles one tick after the click.
    await act(async () => {});
  });

  it("hides the collection action when there are no collections", () => {
    render(<RecipeBulkBar {...baseProps} collections={[]} />);
    expect(
      screen.queryByRole("button", { name: "Add to collection" }),
    ).not.toBeInTheDocument();
  });
});
