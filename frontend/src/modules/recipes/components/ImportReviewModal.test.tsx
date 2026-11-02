import { afterEach, describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import ImportReviewModal from "./ImportReviewModal";
import type { RecipeCreateInput } from "@/modules/recipes/types/core";
import type { RecipeImportPreview } from "@/modules/recipes/types/nutrition";

const unitsRead = vi.hoisted(() => ({ failed: false, refetch: vi.fn() }));
vi.mock("@/modules/shared/hooks/useUoms", () => ({
  useFlatUoms: () => ({
    data: unitsRead.failed
      ? undefined
      : [
          {
            id: "uom-pcs",
            name: "Pieces",
            symbol: "pcs",
            factor: 1,
            rounding: 1,
            is_reference: false,
            category_id: "cat",
          },
        ],
    isError: unitsRead.failed,
    refetch: unitsRead.refetch,
  }),
  useUoms: () => ({ data: [], isLoading: false }),
}));

function preview(): RecipeImportPreview {
  return {
    name: "Bolognese",
    description: null,
    instructions: null,
    servings: 2,
    prep_time_minutes: null,
    image_source_url: null,
    source_url: null,
    tags: [],
    parse_warning: null,
    ingredients: [
      {
        name: "Bay leaf",
        quantity: 1,
        uom_symbol: "pcs",
        uom_id: "uom-pcs",
        original_text: null,
        group_name: null,
        template_id: null,
        template_name: null,
        is_optional: false,
        is_spice: false,
        original_quantity: null,
        original_unit_text: null,
        unit_display: null,
      },
      {
        name: "Salt",
        quantity: 5,
        uom_symbol: "g",
        uom_id: "uom-g",
        original_text: null,
        group_name: null,
        template_id: null,
        template_name: null,
        is_optional: false,
        is_spice: false,
        original_quantity: null,
        original_unit_text: null,
        unit_display: null,
      },
    ],
  };
}

describe("ImportReviewModal — the spice mark reaches the save payload", () => {
  it("preserves imported spice marks and allergens through review edits", () => {
    const imported = preview();
    imported.ingredients[0] = {
      ...imported.ingredients[0],
      is_spice: true,
      allergens: ["mustard"],
    };
    imported.ingredients[1] = {
      ...imported.ingredients[1],
      is_spice: false,
      allergens: ["gluten", "milk"],
    };
    const onSave = vi.fn<(data: RecipeCreateInput) => void>();
    render(
      <ImportReviewModal
        preview={imported}
        onSave={onSave}
        onBack={vi.fn()}
        isSaving={false}
      />,
    );
    expect(screen.getAllByRole("button", { name: "Spice" })[0]).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    fireEvent.change(screen.getByDisplayValue("Bay leaf"), {
      target: { value: "Imported bay leaf" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save recipe" }));
    expect(onSave.mock.calls[0][0].ingredients).toEqual([
      expect.objectContaining({
        name: "Imported bay leaf",
        is_spice: true,
        allergens: ["mustard"],
      }),
      expect.objectContaining({
        name: "Salt",
        is_spice: false,
        allergens: ["gluten", "milk"],
      }),
    ]);
  });

  it("lets the cook clear an imported spice mark without losing allergens", () => {
    const imported = preview();
    imported.ingredients[0] = {
      ...imported.ingredients[0],
      is_spice: true,
      allergens: ["mustard"],
    };
    const onSave = vi.fn<(data: RecipeCreateInput) => void>();
    render(
      <ImportReviewModal
        preview={imported}
        onSave={onSave}
        onBack={vi.fn()}
        isSaving={false}
      />,
    );
    fireEvent.click(screen.getAllByRole("button", { name: "Spice" })[0]);
    fireEvent.click(screen.getByRole("button", { name: "Save recipe" }));
    expect(onSave.mock.calls[0][0].ingredients?.[0]).toMatchObject({
      is_spice: false,
      allergens: ["mustard"],
    });
  });

  it("carries a piece the cook marked as a spice, and only that one", () => {
    const onSave = vi.fn<(data: RecipeCreateInput) => void>();
    render(
      <ImportReviewModal
        preview={preview()}
        onSave={onSave}
        onBack={vi.fn()}
        isSaving={false}
      />,
    );

    const chips = screen.getAllByRole("button", { name: "Spice" });
    // One bay leaf is not a spice by amount; the press is the only mark it has.
    expect(chips[0]).toHaveAttribute("aria-pressed", "false");
    fireEvent.click(chips[0]);
    expect(chips[0]).toHaveAttribute("aria-pressed", "true");

    fireEvent.click(screen.getByRole("button", { name: "Save recipe" }));

    expect(onSave).toHaveBeenCalledTimes(1);
    const ingredients = onSave.mock.calls[0][0].ingredients ?? [];
    expect(ingredients[0]).toMatchObject({ name: "Bay leaf", is_spice: true });
    expect(ingredients[1]).toMatchObject({ name: "Salt", is_spice: false });
  });
});

describe("ImportReviewModal — description and allergens in the review", () => {
  function open(imported: RecipeImportPreview) {
    const onSave = vi.fn<(data: RecipeCreateInput) => void>();
    render(
      <ImportReviewModal
        preview={imported}
        onSave={onSave}
        onBack={vi.fn()}
        isSaving={false}
      />,
    );
    return onSave;
  }

  it("carries the imported description into the create payload", () => {
    const imported = preview();
    imported.description = "Slow-cooked ragù";
    const onSave = open(imported);
    fireEvent.click(screen.getByRole("button", { name: "Save recipe" }));
    expect(onSave.mock.calls[0][0].description).toBe("Slow-cooked ragù");
  });

  it("lets the cook edit the description before saving", () => {
    const imported = preview();
    imported.description = "Slow-cooked ragù";
    const onSave = open(imported);
    fireEvent.change(screen.getByDisplayValue("Slow-cooked ragù"), {
      target: { value: "Sunday ragù" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save recipe" }));
    expect(onSave.mock.calls[0][0].description).toBe("Sunday ragù");
  });

  it("shows the imported allergens on the row and lets the cook change them", () => {
    const imported = preview();
    imported.ingredients[1] = {
      ...imported.ingredients[1],
      allergens: ["gluten", "milk"],
    };
    const onSave = open(imported);
    // Row 2 carries two allergens, row 1 none: the picker trigger says so.
    expect(
      screen.getByRole("button", { name: /2 allergens/ }),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /2 allergens/ }));
    fireEvent.click(screen.getByRole("checkbox", { name: "Milk" }));
    fireEvent.click(screen.getByRole("button", { name: "Save recipe" }));
    expect(onSave.mock.calls[0][0].ingredients?.[1]).toMatchObject({
      name: "Salt",
      allergens: ["gluten"],
    });
  });
});

describe("ImportReviewModal — the units did not load", () => {
  afterEach(() => {
    unitsRead.failed = false;
    unitsRead.refetch.mockClear();
  });

  it("says so, with a retry, instead of judging the imported units against an empty catalogue", () => {
    unitsRead.failed = true;
    render(
      <ImportReviewModal
        preview={preview()}
        onSave={vi.fn()}
        onBack={vi.fn()}
        isSaving={false}
      />,
    );

    expect(screen.getByRole("alert")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /try again/i }));
    expect(unitsRead.refetch).toHaveBeenCalledTimes(1);
  });
});

describe("ImportReviewModal — a unit the import could not read", () => {
  function withUnreadUnit(): RecipeImportPreview {
    const imported = preview();
    imported.ingredients.push({
      ...imported.ingredients[0],
      name: "Soy sauce",
      quantity: 2,
      uom_symbol: null,
      uom_id: null,
      original_unit_text: "tbsp",
    });
    return imported;
  }

  it("names the unit it could not read and will not save the line without one", () => {
    const onSave = vi.fn<(data: RecipeCreateInput) => void>();
    render(
      <ImportReviewModal
        preview={withUnreadUnit()}
        onSave={onSave}
        onBack={vi.fn()}
        isSaving={false}
      />,
    );

    expect(screen.getByTestId("unit-unread")).toHaveTextContent("tbsp");
    expect(screen.getByRole("status")).toBeInTheDocument();
    const save = screen.getByRole("button", { name: "Save recipe" });
    expect(save).toBeDisabled();
    fireEvent.click(save);
    expect(onSave).not.toHaveBeenCalled();
  });

  it("saves once every named line has a unit", () => {
    const imported = withUnreadUnit();
    imported.ingredients[2] = { ...imported.ingredients[2], uom_id: "uom-pcs" };
    const onSave = vi.fn<(data: RecipeCreateInput) => void>();
    render(
      <ImportReviewModal
        preview={imported}
        onSave={onSave}
        onBack={vi.fn()}
        isSaving={false}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Save recipe" }));
    expect(onSave).toHaveBeenCalledTimes(1);
  });
});
