import { StrictMode } from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import {
  render,
  screen,
  fireEvent,
  waitFor,
  act,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { queryKeys } from "@/hooks/queries/keys";
import RecipeForm from "./RecipeForm";
import { recipesApi } from "@/modules/recipes/api/recipes";
import type { IngredientDefaultLookupResponse } from "@/modules/recipes/types/nutrition-defaults";

vi.mock("../hooks/useIngredientDefaults", () => ({
  useDebouncedIngredientLookup: () => vi.fn(),
}));

const image = vi.hoisted(() => ({ upload: vi.fn(), remove: vi.fn() }));

vi.mock("../hooks/useRecipes", () => ({
  useUploadRecipeImage: () => ({ mutate: image.upload, isPending: false }),
  useDeleteRecipeImage: () => ({ mutate: image.remove }),
}));

// The advanced row fields mount the "always at home" toggle, whose shopping
// exclusions need the modules context this render does not carry.
vi.mock("../hooks/useMealPlans", () => ({
  useShoppingExclusions: () => ({ data: [], isLoading: false }),
  useCreateShoppingExclusion: () => ({ mutate: vi.fn(), isPending: false }),
  useDeleteShoppingExclusion: () => ({ mutate: vi.fn(), isPending: false }),
}));

function renderForm(
  props: React.ComponentProps<typeof RecipeForm>,
  options?: { strict?: boolean; seedUoms?: boolean },
) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  if (options?.seedUoms) {
    client.setQueryData(queryKeys.uoms.categories, [
      {
        id: "weight",
        name: "Weight",
        uoms: [
          {
            id: "gram",
            category_id: "weight",
            name: "Gram",
            symbol: "g",
            factor: 1,
            is_reference: true,
          },
        ],
      },
    ]);
  }
  const form = (
    <QueryClientProvider client={client}>
      <RecipeForm {...props} />
    </QueryClientProvider>
  );
  return render(options?.strict ? <StrictMode>{form}</StrictMode> : form);
}

const originalCreateObjectURL = URL.createObjectURL;
const originalRevokeObjectURL = URL.revokeObjectURL;

beforeEach(() => {
  URL.createObjectURL = vi.fn(() => "blob:preview");
  URL.revokeObjectURL = vi.fn();
});

afterEach(() => {
  URL.createObjectURL = originalCreateObjectURL;
  URL.revokeObjectURL = originalRevokeObjectURL;
});

describe("RecipeForm — leaving a filled form", () => {
  // Four ways out and every one of them threw the recipe away without a word:
  // Escape, the cross, the backdrop, Cancel. The longest form in the module,
  // no draft, no way back.
  const fillIn = () =>
    fireEvent.change(screen.getByPlaceholderText("e.g. Pasta Bolognese"), {
      target: { value: "Grandmother's pierogi" },
    });

  it("asks before Escape discards what was typed", () => {
    const onCancel = vi.fn();
    renderForm({ onSubmit: vi.fn(), onCancel });
    fillIn();

    fireEvent.keyDown(document, { key: "Escape" });

    expect(onCancel).not.toHaveBeenCalled();
    expect(screen.getByText("Discard changes?")).toBeInTheDocument();
  });

  it("lets Escape go when the list inside the sheet is open", () => {
    // The press was aimed at the unit list, not at the form.
    const onCancel = vi.fn();
    renderForm({ onSubmit: vi.fn(), onCancel });
    fillIn();

    const popper = document.createElement("div");
    popper.setAttribute("data-radix-popper-content-wrapper", "");
    document.body.appendChild(popper);
    fireEvent.keyDown(document, { key: "Escape" });
    popper.remove();

    expect(onCancel).not.toHaveBeenCalled();
    expect(screen.queryByText("Discard changes?")).not.toBeInTheDocument();
  });

  it("asks before the Cancel button discards it, and leaves on confirmation", () => {
    const onCancel = vi.fn();
    renderForm({ onSubmit: vi.fn(), onCancel });
    fillIn();

    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(onCancel).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Discard" }));
    expect(onCancel).toHaveBeenCalledTimes(1);
  });

  it("does not ask when nothing was typed", () => {
    const onCancel = vi.fn();
    renderForm({ onSubmit: vi.fn(), onCancel });

    fireEvent.keyDown(document, { key: "Escape" });

    expect(onCancel).toHaveBeenCalledTimes(1);
  });
});

describe("RecipeForm — photo", () => {
  it("hands the picked photo to onSubmit in create mode", async () => {
    const onSubmit = vi.fn();
    renderForm({ onSubmit, onCancel: vi.fn() });

    // Photo section present with the empty placeholder
    expect(screen.getByText("No photo yet")).toBeInTheDocument();

    fireEvent.change(screen.getByPlaceholderText("e.g. Pasta Bolognese"), {
      target: { value: "Pancakes" },
    });

    const file = new File(["photo"], "photo.jpg", { type: "image/jpeg" });
    fireEvent.change(screen.getByLabelText("Add photo"), {
      target: { files: [file] },
    });

    // Local preview appears
    await waitFor(() => {
      expect(screen.getByAltText("Photo")).toHaveAttribute(
        "src",
        "blob:preview",
      );
    });

    fireEvent.click(screen.getByText("Save"));
    expect(onSubmit).toHaveBeenCalledTimes(1);
    expect(onSubmit.mock.calls[0][1]).toBe(file);
  });

  it("uploads straight to the recipe in edit mode", async () => {
    const onSubmit = vi.fn();
    renderForm({
      initial: { id: "r1", name: "Existing", image_url: "http://img/1" },
      onSubmit,
      onCancel: vi.fn(),
    });

    // Existing photo is shown
    expect(screen.getByAltText("Photo")).toHaveAttribute("src", "http://img/1");

    const file = new File(["photo"], "photo.jpg", { type: "image/jpeg" });
    fireEvent.change(screen.getByLabelText("Add photo"), {
      target: { files: [file] },
    });
  });

  it("leaves a refused upload and delete in edit mode to the factory's toast", () => {
    // Nothing awaits either one, so `mutate` with no `onError` of its own:
    // the mutation factory says the refusal. The catch that stood here once
    // said nothing, trusting a parent toast that never came.
    renderForm({
      initial: { id: "r1", name: "Existing", image_url: "http://img/1" },
      onSubmit: vi.fn(),
      onCancel: vi.fn(),
    });

    const file = new File(["photo"], "photo.jpg", { type: "image/jpeg" });
    fireEvent.change(screen.getByLabelText("Add photo"), {
      target: { files: [file] },
    });
    fireEvent.click(screen.getByRole("button", { name: "Delete photo" }));

    expect(image.upload).toHaveBeenCalledWith({ id: "r1", file });
    expect(image.upload.mock.calls[0]).toHaveLength(1);
    expect(image.remove).toHaveBeenCalledWith("r1");
    expect(image.remove.mock.calls[0]).toHaveLength(1);
  });
});

describe("RecipeForm — label consistency", () => {
  it("writes every field label the one way the field components do", () => {
    renderForm({ onSubmit: vi.fn(), onCancel: vi.fn() });
    // Description used to opt out of the shared variant with a
    // `labelClassName` that undid the uppercase, so this form carried two
    // label styles in one column.
    for (const text of [
      "Recipe name",
      "Description",
      "Servings",
      "Tags (comma-separated)",
    ]) {
      expect(screen.getByText(text).closest("label")).toHaveClass("uppercase");
    }
  });

  it("names the ingredient quantity field the row does not label visibly", () => {
    renderForm({ onSubmit: vi.fn(), onCancel: vi.fn() });

    // The repeating row carries no visible label — the column position says
    // it to the eye; the field must still say it to the tree.
    expect(
      screen.getByRole("spinbutton", { name: "Quantity" }),
    ).toBeInTheDocument();
  });
});

describe("RecipeForm — field order", () => {
  it("puts ingredients and instructions before the photo box", () => {
    renderForm({ onSubmit: vi.fn(), onCancel: vi.fn() });

    const ingredients = screen.getByText("Ingredients");
    const instructions = screen.getByText("Instructions");
    const photo = screen.getByText("Photo");

    const before = (a: HTMLElement, b: HTMLElement) =>
      Boolean(a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING);

    expect(before(ingredients, photo)).toBe(true);
    expect(before(instructions, photo)).toBe(true);
  });

  it("keeps the quantity input wrapper at a fixed width instead of full-width", () => {
    const { container } = renderForm({ onSubmit: vi.fn(), onCancel: vi.fn() });

    // With "more options" collapsed, the only number input is the quantity.
    const qtyInput = container.querySelector('input[type="number"]');
    expect(qtyInput).not.toBeNull();
    const wrapper = qtyInput!.parentElement!.parentElement;
    expect(wrapper).toHaveClass("w-16");
    expect(wrapper).toHaveClass("shrink-0");
    expect(wrapper).not.toHaveClass("w-full");
  });
});

describe("RecipeForm — new ingredient picking", () => {
  it("leaves a new ingredient to the picking heuristic", async () => {
    const onSubmit = vi.fn();
    renderForm({ onSubmit, onCancel: vi.fn() }, { seedUoms: true });

    fireEvent.change(screen.getByPlaceholderText("e.g. Pasta Bolognese"), {
      target: { value: "Soup" },
    });
    fireEvent.change(screen.getByLabelText("Ingredient name"), {
      target: { value: "Pepper" },
    });
    fireEvent.change(screen.getByRole("spinbutton", { name: "Quantity" }), {
      target: { value: "5" },
    });
    const unit = await screen.findByRole("button", { name: /unit choose/i });
    await waitFor(() => expect(unit).toBeEnabled());
    await userEvent.click(unit);
    await userEvent.click(await screen.findByRole("button", { name: /gram/i }));
    fireEvent.click(screen.getByText("Save"));

    expect(onSubmit).toHaveBeenCalledOnce();
    expect(onSubmit.mock.calls[0][0].ingredients[0].picking_skip).toBeNull();
  });
});

describe("RecipeForm — ingredient identity on edit", () => {
  it("sends each existing ingredient back with its id", () => {
    const onSubmit = vi.fn();
    renderForm({
      initial: {
        id: "r1",
        name: "Bread",
        servings: 2,
        ingredients: [
          {
            id: "ing-1",
            recipe_id: "r1",
            name: "Flour",
            template_id: null,
            ingredient_group_name: null,
            quantity: "200",
            uom_id: "uom-g",
            uom_symbol: "g",
            is_optional: false,
            is_spice: false,
            picking_skip: null,
            sort_order: 0,
            calories_kcal_per_100g: null,
            display_text: null,
            original_quantity: null,
            original_unit_text: null,
            price: null,
            price_uom_id: null,
            price_currency: null,
            allergens: [],
          },
        ],
      },
      onSubmit,
      onCancel: vi.fn(),
    });

    fireEvent.click(screen.getByText("Save"));

    // Without the id the backend cannot tell an edit from a replacement, and
    // replacing the row detaches the picking sessions that consumed it.
    expect(onSubmit.mock.calls[0][0].ingredients[0].id).toBe("ing-1");
  });

  it("keeps an ingredient's automatic picking override (null) when saved unchanged", () => {
    const onSubmit = vi.fn();
    renderForm({
      initial: {
        id: "r1",
        name: "Bread",
        servings: 2,
        ingredients: [
          {
            id: "ing-1",
            recipe_id: "r1",
            name: "Black pepper",
            template_id: null,
            ingredient_group_name: null,
            quantity: "5",
            uom_id: "uom-g",
            uom_symbol: "g",
            is_optional: false,
            is_spice: false,
            picking_skip: null,
            sort_order: 0,
            calories_kcal_per_100g: null,
            display_text: null,
            original_quantity: null,
            original_unit_text: null,
            price: null,
            price_uom_id: null,
            price_currency: null,
            allergens: [],
          },
        ],
      },
      onSubmit,
      onCancel: vi.fn(),
    });

    fireEvent.click(screen.getByText("Save"));

    // null leaves the call to the server's heuristic; false would pin the row
    // as "never skip" and change what the picking session shows.
    expect(onSubmit.mock.calls[0][0].ingredients[0].picking_skip).toBeNull();
  });
});

describe("RecipeForm — an amount needs a unit", () => {
  it("refuses to save an ingredient line with a quantity and no unit", () => {
    // "Salt, 1" with the unit left at "Choose" was saved, and became
    // "Uncountable 1" on the recipe and "1 —" on the shopping list.
    const onSubmit = vi.fn();
    renderForm({
      initial: {
        id: "r2",
        name: "QA No Unit",
        servings: 1,
        ingredients: [
          {
            id: "ing-salt",
            recipe_id: "r2",
            name: "Salt",
            template_id: null,
            ingredient_group_name: null,
            quantity: "1",
            uom_id: null,
            uom_symbol: null,
            is_optional: false,
            is_spice: false,
            picking_skip: null,
            sort_order: 0,
            calories_kcal_per_100g: null,
            display_text: null,
            original_quantity: null,
            original_unit_text: null,
            price: null,
            price_uom_id: null,
            price_currency: null,
            allergens: [],
          },
        ],
      },
      onSubmit,
      onCancel: vi.fn(),
    });

    fireEvent.click(screen.getByText("Save"));

    expect(onSubmit).not.toHaveBeenCalled();
    expect(screen.getByText("Choose a unit")).toBeInTheDocument();
  });
});

describe("RecipeForm — clearing a field saves it as empty", () => {
  // The four clearable fields used to go out as `undefined` when emptied,
  // the server's exclude_unset kept the old values, and a recipe carried
  // an unwanted description forever.
  const initial = {
    id: "r1",
    organization_id: "o1",
    created_by: "u1",
    name: "Pierogi",
    description: "Old description",
    instructions: "Old instructions",
    servings: 4,
    prep_time_minutes: 30,
    image_url: null,
    source_url: null,
    tags: ["dinner"],
    is_favorite: false,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    ingredients: [],
    allergens: [],
  } as React.ComponentProps<typeof RecipeForm>["initial"];

  it("sends explicit nulls for cleared description, instructions, prep time and tags", async () => {
    const onSubmit = vi.fn();
    renderForm({ initial, onSubmit, onCancel: vi.fn() });

    fireEvent.change(screen.getByLabelText("Description"), {
      target: { value: "" },
    });
    fireEvent.change(
      screen.getByPlaceholderText("Step by step cooking instructions…"),
      { target: { value: "" } },
    );
    fireEvent.change(screen.getByLabelText("Prep time (min)"), {
      target: { value: "" },
    });
    fireEvent.change(screen.getByLabelText("Tags (comma-separated)"), {
      target: { value: "" },
    });

    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(onSubmit).toHaveBeenCalled());
    const payload = onSubmit.mock.calls[0][0];
    expect(payload.description).toBeNull();
    expect(payload.instructions).toBeNull();
    expect(payload.prep_time_minutes).toBeNull();
    expect(payload.tags).toBeNull();
    // The untouched required fields keep their values.
    expect(payload.name).toBe("Pierogi");
    expect(payload.servings).toBe(4);
  });
});

describe("RecipeForm — ingredient defaults are looked up once", () => {
  // Autofill used to re-arm itself. A lookup that answers with allergens but no
  // kcal leaves the ingredient in `missing`; the effect wrote state on every
  // answer and carried `ingredients` in its deps, so the fresh array identity
  // started the whole thing again — one ingredient, a steady stream of GETs for
  // as long as the dialog stayed open.
  const ingredient = (id: string, name: string, sortOrder: number) => ({
    id,
    recipe_id: "r1",
    name,
    template_id: null,
    ingredient_group_name: null,
    quantity: "200",
    uom_id: null,
    uom_symbol: null,
    is_optional: false,
    is_spice: false,
    picking_skip: null,
    sort_order: sortOrder,
    calories_kcal_per_100g: null,
    display_text: null,
    original_quantity: null,
    original_unit_text: null,
    price: null,
    price_uom_id: null,
    price_currency: null,
    allergens: [],
  });
  const answer = (
    name: string,
    calories: number | null,
    allergens: string[],
  ): IngredientDefaultLookupResponse => ({
    found: calories != null || allergens.length > 0,
    name,
    lang: "en",
    calories_kcal: calories === null ? null : String(calories),
    protein_g: null,
    fat_g: null,
    carbs_g: null,
    fiber_g: null,
    sugar_g: null,
    salt_g: null,
    source: null,
    allergens,
  });

  it("fills the answers under StrictMode and asks each ingredient once", async () => {
    // The app mounts inside StrictMode (main.tsx): setup, cleanup, setup in the
    // same commit. Latching a name before its answer arrived burned it — the
    // surviving pass found nothing to ask, the cancelled first pass dropped the
    // fill, and the picker stayed empty while the network was quiet. RTL does
    // not wrap in StrictMode on its own, so this render does.
    const calls: string[] = [];
    const spy = vi
      .spyOn(recipesApi, "lookupIngredientDefault")
      .mockImplementation((name: string) => {
        calls.push(name);
        return Promise.resolve(
          name === "Flour"
            ? answer("Flour", null, ["gluten"])
            : answer(name, 700, []),
        );
      });

    try {
      renderForm(
        {
          initial: {
            id: "r1",
            name: "Bread",
            servings: 2,
            ingredients: [
              ingredient("ing-1", "Flour", 0),
              ingredient("ing-2", "Butter", 1),
            ],
          },
          onSubmit: vi.fn(),
          onCancel: vi.fn(),
        },
        { strict: true },
      );

      await waitFor(() => expect(calls).toEqual(["Flour", "Butter"]));

      fireEvent.click(
        screen.getAllByRole("button", { name: "More options" })[0],
      );
      fireEvent.click(
        screen.getAllByRole("button", { name: "More options" })[1],
      );

      // Both answers landed: allergens-but-no-kcal on the first row, kcal on
      // the second. The burned once-guard asked only the first and applied
      // neither.
      expect(await screen.findByText("1 allergen")).toBeInTheDocument();
      expect(screen.getByText("700 kcal/100g")).toBeInTheDocument();

      // Let the turns a re-armed effect would need pass; the count must hold.
      await act(async () => {
        await Promise.resolve();
        await Promise.resolve();
      });
      expect(calls).toEqual(["Flour", "Butter"]);
    } finally {
      spy.mockRestore();
    }
  });
});
