import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { CategoryField } from "./CategoryField";
import type { CategoryDTO } from "@/types";

const dairy: CategoryDTO = {
  is_module_owned: false,
  id: "cat-dairy",
  name: "Dairy",
  code: null,
  context_tag: null,
  icon: null,
  sort_order: 1,
  is_active: true,
};

const laptop: CategoryDTO = {
  ...dairy,
  id: "cat-equipment",
  name: "Laptop",
  code: "laptop",
  context_tag: "equipment",
  module_name: "equipment",
  is_module_owned: true,
};

describe("CategoryField — a category a module owns", () => {
  it("says before the save that the record stops being a product", () => {
    // The picker offers it (the organization opted into showing module
    // data, or the record came in filed under it) — so the screen owes the
    // reader the consequence while there is still time not to save.
    render(
      <CategoryField
        value="cat-equipment"
        categories={[dairy, laptop]}
        onChange={() => {}}
      />,
    );

    const warning = screen.getByTestId("category-module-warning");
    expect(warning).toHaveTextContent("Laptop");
    expect(warning).toHaveTextContent("Equipment Tracking");
  });

  it("says nothing about an ordinary category", () => {
    render(
      <CategoryField
        value="cat-dairy"
        categories={[dairy, laptop]}
        onChange={() => {}}
      />,
    );

    expect(
      screen.queryByTestId("category-module-warning"),
    ).not.toBeInTheDocument();
  });

  it("names an equipment category in the reader's language, like its food neighbours", async () => {
    // The picker resolves every category through the shared catalogue; an
    // equipment record's code stands beside food codes in the same list, so
    // a missing entry does not read like a missing translation — it reads
    // like the seed's English literal dropped into a Polish form.
    const { withLanguage } = await import("@/test/mocks/i18n");
    const desktop = {
      ...dairy,
      id: "cat-desktop",
      name: "Desktop Computer",
      code: "DESKTOP",
      context_tag: "equipment",
      module_name: "equipment",
      is_module_owned: true,
    };

    await withLanguage("pl", () => {
      render(
        <CategoryField
          value="cat-desktop"
          categories={[dairy, desktop]}
          onChange={() => {}}
        />,
      );

      // Assertions stay inside: withLanguage restores English on the way
      // out, and the mounted picker follows.
      expect(screen.getByText("Komputer stacjonarny")).toBeInTheDocument();
      expect(screen.queryByText("Desktop Computer")).not.toBeInTheDocument();
    });
  });
});
