import { http, HttpResponse } from "msw";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@/test/utils";
import { server } from "@/test/mocks/server";
import { LabelFactsSlot } from "@/modules/maker/components/LabelFactsSlot";
import type { LabelFacts } from "@/modules/maker/types/maker";
import type { Item } from "@/types";

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
vi.mock("@/hooks/useCanWrite", () => ({
  useCanWrite: () => true,
  useCanManage: () => true,
}));

const item = {
  template_id: "tpl-butter",
  template: { name: "Butter" },
} as unknown as Item;

const unchecked: LabelFacts = {
  product_template_id: "tpl-butter",
  label_name: null,
  allergens: null,
  may_contain: [],
  suggested_allergens: ["milk"],
  recipe_id: null,
  derived_allergens: [],
  derived_may_contain: [],
};

let answered = 0;

function serve(facts: LabelFacts, usedIn: number) {
  server.use(
    http.get("*/api/v1/maker/labelling/products/:id", () => {
      answered += 1;
      return HttpResponse.json(facts);
    }),
    http.get("*/api/v1/maker/bom/where-used", () => {
      answered += 1;
      return HttpResponse.json({
        items: Array.from({ length: usedIn }, (_, i) => ({
          recipe_id: `recipe-${i}`,
          recipe_name: "Shortbread",
          output_template_id: "tpl-shortbread",
          output_name: "Shortbread",
          qty_per_batch: "100",
          unit: "g",
        })),
      });
    }),
  );
}

describe("LabelFactsSlot", () => {
  let saved: unknown;

  beforeEach(() => {
    saved = undefined;
    answered = 0;
    server.use(
      http.put("*/api/v1/maker/labelling/products/:id", async ({ request }) => {
        saved = await request.json();
        return HttpResponse.json({
          ...unchecked,
          ...(saved as object),
        });
      }),
    );
  });

  it("offers what an ingredient's name suggests, and saves it only once confirmed", async () => {
    serve(unchecked, 1);
    render(<LabelFactsSlot data={{ item }} />);

    expect(
      await screen.findByText(
        "Allergens not checked yet. The name suggests: Milk.",
      ),
    ).toBeInTheDocument();
    expect(saved).toBeUndefined();

    fireEvent.click(screen.getByTestId("maker-label-confirm-suggestion"));

    await waitFor(() =>
      expect(saved).toEqual({
        label_name: null,
        allergens: ["milk"],
        may_contain: [],
      }),
    );
  });

  it("says a checked product contains none, and what it may contain", async () => {
    serve({ ...unchecked, allergens: [], may_contain: ["nuts"] }, 1);
    render(<LabelFactsSlot data={{ item }} />);

    expect(await screen.findByTestId("maker-label-contains")).toHaveTextContent(
      "None",
    );
    expect(screen.getByTestId("maker-label-may-contain")).toHaveTextContent(
      "Nuts",
    );
  });

  it("shows a made product's allergens with the ingredient that brings each", async () => {
    serve(
      {
        ...unchecked,
        product_template_id: "tpl-cake",
        allergens: ["sesame"],
        recipe_id: "recipe-cake",
        derived_allergens: [
          {
            allergen: "gluten",
            sources: [{ template_id: "tpl-flour", name: "Wheat flour" }],
            declared_on_product: false,
          },
          {
            allergen: "sesame",
            sources: [],
            declared_on_product: true,
          },
        ],
      },
      0,
    );
    render(<LabelFactsSlot data={{ item }} />);

    expect(await screen.findByTestId("maker-label-contains")).toHaveTextContent(
      "Sesame",
    );
    expect(screen.getByText("Declared on this product")).toBeInTheDocument();
    const derived = screen.getByTestId("maker-label-derived");
    expect(derived).toHaveTextContent("Gluten — from Wheat flour");
    expect(derived).toHaveTextContent("Sesame — declared on the product");
    expect(
      screen.getByText(/Computed from the BOM and its ingredients' cards/),
    ).toBeInTheDocument();
  });

  it("keeps the name a product goes under in a list when the field is left", async () => {
    serve({ ...unchecked, allergens: ["gluten"] }, 1);
    render(<LabelFactsSlot data={{ item }} />);

    const field = await screen.findByTestId("maker-label-name-input");
    fireEvent.change(field, { target: { value: "Wheat flour" } });
    fireEvent.blur(field);

    await waitFor(() =>
      expect(saved).toEqual({
        label_name: "Wheat flour",
        allergens: ["gluten"],
        may_contain: [],
      }),
    );
  });

  it("does not ask a made product to check what its BOM already answers", async () => {
    serve(
      { ...unchecked, recipe_id: "recipe-cake", suggested_allergens: [] },
      0,
    );
    render(<LabelFactsSlot data={{ item }} />);

    expect(await screen.findByTestId("maker-label-contains")).toHaveTextContent(
      "None",
    );
    expect(screen.queryByTestId("maker-label-unchecked")).toBeNull();
  });

  it("stays away from a product no formula touches", async () => {
    serve(unchecked, 0);
    render(<LabelFactsSlot data={{ item }} />);

    // Both answers are in, and still nothing: not a slot waiting to load.
    await waitFor(() => expect(answered).toBe(2));
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(screen.queryByTestId("maker-label-facts")).toBeNull();
  });
});
