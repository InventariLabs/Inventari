import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ProductTemplate } from "@/lib/api/productTemplates";
import IngredientLinkButton from "./IngredientLinkButton";

const link = vi.fn().mockResolvedValue(undefined);
vi.mock("../hooks/useRecipes", () => ({
  useLinkIngredientTemplate: () => ({ mutateAsync: link }),
}));

const productSearch = vi.fn<(query: string) => Promise<ProductTemplate[]>>();
const createProduct =
  vi.fn<(name: string, uomId: string) => Promise<ProductTemplate>>();
vi.mock("@/lib/api/productTemplates", () => ({
  productTemplatesApi: {
    search: (query: string) => productSearch(query),
    create: (name: string, uomId: string) => createProduct(name, uomId),
  },
}));

vi.mock("@/modules/shared/hooks/useUoms", () => ({
  useFlatUoms: () => ({
    data: [
      { id: "uom-kg", name: "Kilogram", symbol: "kg" },
      { id: "uom-g", name: "Gram", symbol: "g" },
    ],
  }),
}));

function product(name: string, id = "tpl-new"): ProductTemplate {
  return {
    id,
    name,
    sku: null,
    barcode: null,
    image_url: null,
    uom_id: "uom-g",
  } as ProductTemplate;
}

function renderButton(
  props: Partial<React.ComponentProps<typeof IngredientLinkButton>> = {},
) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  invalidate = vi.spyOn(client, "invalidateQueries");
  return render(
    <QueryClientProvider client={client}>
      <IngredientLinkButton ingredientId="ing-1" recipeId="rec-1" {...props} />
    </QueryClientProvider>,
  );
}

let invalidate: ReturnType<typeof vi.spyOn>;

beforeEach(() => {
  vi.clearAllMocks();
  productSearch.mockResolvedValue([]);
});

describe("IngredientLinkButton — shared product search", () => {
  it("searches the catalogue through the shared combobox, not a raw input", async () => {
    const user = userEvent.setup();
    renderButton();

    await user.click(screen.getByRole("button", { name: "Link to product" }));

    // The hand-rolled predecessor was a bare <input> with a hand-rolled list:
    // no combobox role, no listbox to point at, no keyboard.
    const search = screen.getByRole("combobox");
    expect(search).toHaveAttribute("aria-autocomplete", "list");
    expect(search).toHaveAttribute("aria-expanded", "false");
  });
});

describe("IngredientLinkButton — nothing in the catalogue matches", () => {
  it("creates the product from the ingredient and links it in the same action", async () => {
    const user = userEvent.setup();
    createProduct.mockResolvedValue(product("Mąka pszenna"));
    const onLinked = vi.fn();
    renderButton({
      ingredientName: "Mąka pszenna",
      uomSymbol: "g",
      onLinked,
    });

    await user.click(screen.getByRole("button", { name: "Link to product" }));

    // The box opens on the ingredient's name and has already asked the
    // catalogue: nothing to type before the empty answer is on screen.
    expect(
      await screen.findByTestId("ingredient-link-search-input"),
    ).toHaveValue("Mąka pszenna");
    const create = await screen.findByTestId("ingredient-link-search-create");
    // The unit is the ingredient's own, so nothing is left to ask.
    expect(create).toBeEnabled();
    expect(screen.getByTestId("ingredient-link-search-uom")).toHaveValue(
      "uom-g",
    );

    await user.click(create);

    await waitFor(() =>
      expect(createProduct).toHaveBeenCalledWith("Mąka pszenna", "uom-g"),
    );
    await waitFor(() =>
      expect(link).toHaveBeenCalledWith({
        ingredientId: "ing-1",
        templateId: "tpl-new",
      }),
    );
    expect(onLinked).toHaveBeenCalledTimes(1);
    // The catalogue now holds a product: screens that gate on "is it empty"
    // must hear about it.
    expect(invalidate).toHaveBeenCalledWith({
      queryKey: ["product-templates", "count"],
    });
  });

  it("links an existing match without creating anything", async () => {
    const user = userEvent.setup();
    productSearch.mockResolvedValue([product("Mąka tortowa", "tpl-existing")]);
    renderButton({ ingredientName: "Mąka", uomSymbol: "g" });

    await user.click(screen.getByRole("button", { name: "Link to product" }));
    await user.click(
      await screen.findByTestId("ingredient-link-search-result"),
    );

    await waitFor(() =>
      expect(link).toHaveBeenCalledWith({
        ingredientId: "ing-1",
        templateId: "tpl-existing",
      }),
    );
    expect(createProduct).not.toHaveBeenCalled();
  });
});

describe("IngredientLinkButton — the create is refused", () => {
  it("keeps the typed name in the box, so it can be shortened and sent again", async () => {
    const user = userEvent.setup();
    createProduct.mockRejectedValue(new Error("refused"));
    renderButton({ ingredientName: "Mąka", uomSymbol: "g" });

    await user.click(screen.getByRole("button", { name: "Link to product" }));
    const input = await screen.findByTestId("ingredient-link-search-input");
    await user.clear(input);
    await user.type(input, "Mąka pszenna typ 650 z młyna pod lasem");
    await user.click(
      await screen.findByTestId("ingredient-link-search-create"),
    );

    await waitFor(() => expect(createProduct).toHaveBeenCalled());
    // What a browser does next with a name wider than the box: it scrolls
    // the text inside the input, and that scroll used to clear the box.
    fireEvent.scroll(input);
    expect(
      await screen.findByTestId("ingredient-link-search-input"),
    ).toHaveValue("Mąka pszenna typ 650 z młyna pod lasem");
    expect(link).not.toHaveBeenCalled();
  });

  it("holds the name to the length a product name may have", async () => {
    const user = userEvent.setup();
    renderButton({ ingredientName: "Mąka", uomSymbol: "g" });

    await user.click(screen.getByRole("button", { name: "Link to product" }));

    expect(
      await screen.findByTestId("ingredient-link-search-input"),
    ).toHaveAttribute("maxLength", "255");
  });
});
