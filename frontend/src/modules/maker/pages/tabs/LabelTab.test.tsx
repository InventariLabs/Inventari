import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import { render, screen } from "@/test/utils";
import { server } from "@/test/mocks/server";
import { LabelTab } from "@/modules/maker/pages/tabs/LabelTab";
import type { MakerRecipe, RecipeLabel } from "@/modules/maker/types/maker";

const recipe = {
  id: "recipe-cake",
  output_template_id: "tpl-cake",
} as unknown as MakerRecipe;

const label: RecipeLabel = {
  recipe_id: "recipe-cake",
  output_template_id: "tpl-cake",
  text: "Ingredients: Dough (WHEAT FLOUR, BUTTER), Plums, Vanilla pod.",
  ingredients: [
    {
      template_id: "tpl-dough",
      name: "Dough",
      weight_g: "600.00",
      emphasised: false,
      children: [
        {
          template_id: "tpl-flour",
          name: "Wheat flour",
          weight_g: "200.00",
          emphasised: true,
          children: [],
        },
        {
          template_id: "tpl-butter",
          name: "Butter",
          weight_g: "100.00",
          emphasised: true,
          children: [],
        },
      ],
    },
    {
      template_id: "tpl-plums",
      name: "Plums",
      weight_g: "400.00",
      emphasised: false,
      children: [],
    },
    {
      template_id: "tpl-vanilla",
      name: "Vanilla pod",
      weight_g: null,
      emphasised: false,
      children: [],
    },
  ],
  allergens: [
    {
      allergen: "gluten",
      sources: [{ template_id: "tpl-flour", name: "Wheat flour" }],
      declared_on_product: false,
    },
    {
      allergen: "milk",
      sources: [{ template_id: "tpl-butter", name: "Butter" }],
      declared_on_product: false,
    },
  ],
  may_contain: [
    {
      allergen: "nuts",
      sources: [{ template_id: "tpl-plums", name: "Plums" }],
      declared_on_product: false,
    },
  ],
  unchecked: [
    {
      template_id: "tpl-vanilla",
      name: "Vanilla pod",
      suggested_allergens: [],
    },
  ],
  unweighed: [{ template_id: "tpl-vanilla", name: "Vanilla pod" }],
  yield_weight_g: "900.00",
  nutrition: {
    energy_kj: "1098",
    energy_kcal: "263",
    fat: "0.9",
    saturates: null,
    carbohydrate: "54.0",
    sugars: "1.1",
    protein: "7.5",
    salt: "0.00",
    missing: [
      { template_id: "tpl-plums", name: "Plums", nutrients: ["saturates"] },
      {
        template_id: "tpl-vanilla",
        name: "Vanilla pod",
        nutrients: [
          "energy_kcal",
          "fat",
          "saturates",
          "carbohydrate",
          "sugars",
          "protein",
          "salt",
        ],
      },
    ],
  },
};

function serve(body: RecipeLabel) {
  server.use(
    http.get("*/api/v1/maker/labelling/recipes/:id", () =>
      HttpResponse.json(body),
    ),
  );
}

describe("LabelTab", () => {
  it("writes the list heaviest first, a made ingredient's own in brackets, allergens emphasised", async () => {
    serve(label);
    render(<LabelTab recipe={recipe} />);

    const list = await screen.findByTestId("maker-label-list");
    expect(list).toHaveTextContent(
      "Dough (Wheat flour, Butter), Plums, Vanilla pod",
    );
    const emphasised = Array.from(list.querySelectorAll("strong")).map(
      (node) => node.textContent,
    );
    expect(emphasised).toEqual(["Wheat flour", "Butter"]);
    expect(
      screen.getByText(/Computed from the BOM and its ingredients' cards/),
    ).toBeInTheDocument();
  });

  it("names what it could not settle: unchecked and unweighed ingredients", async () => {
    serve(label);
    render(<LabelTab recipe={recipe} />);

    const doubts = await screen.findByTestId("maker-label-doubts");
    expect(doubts).toHaveTextContent(
      "Not checked for allergens yet: Vanilla pod",
    );
    expect(doubts).toHaveTextContent("so the list puts them last: Vanilla pod");
  });

  it("gives each allergen with the ingredients that bring it", async () => {
    serve(label);
    render(<LabelTab recipe={recipe} />);

    const allergens = await screen.findByTestId("maker-label-allergens");
    expect(allergens).toHaveTextContent("Gluten — from Wheat flour");
    expect(allergens).toHaveTextContent("Milk — from Butter");
    expect(
      screen.getByTestId("maker-label-may-contain-list"),
    ).toHaveTextContent("Nuts — from Plums");
  });

  it("declares per 100 g and leaves a figure an ingredient lacks unknown, naming it", async () => {
    serve(label);
    render(<LabelTab recipe={recipe} />);

    const table = await screen.findByTestId("maker-label-nutrition");
    expect(table).toHaveTextContent("Energy1,098 kJ / 263 kcal");
    expect(table).toHaveTextContent("of which saturatesnot known");
    expect(table).toHaveTextContent("Salt0 g");
    const missing = screen.getByTestId("maker-label-missing");
    expect(missing).toHaveTextContent("Plums has no figure for saturates");
    expect(missing).toHaveTextContent("Vanilla pod has no figures");
    expect(
      screen.getByText("Per 100 g of the 900 g one batch yields."),
    ).toBeInTheDocument();
  });

  it("says there is no declaration when no ingredient carries a figure", async () => {
    serve({ ...label, nutrition: null });
    render(<LabelTab recipe={recipe} />);

    expect(
      await screen.findByTestId("maker-label-no-nutrition"),
    ).toBeInTheDocument();
  });
});
