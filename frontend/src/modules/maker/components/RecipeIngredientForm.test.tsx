import { render, screen, waitFor } from "@/test/utils";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { RecipeIngredientForm } from "./RecipeIngredientForm";
import { recipeApi } from "@/modules/maker/api/recipes";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

vi.mock("@/modules/maker/api/recipes", () => ({
  recipeApi: { addBomLine: vi.fn() },
}));

const unitsRead = vi.hoisted(() => ({ failed: false }));
vi.mock("@/modules/shared/hooks/useUoms", () => ({
  useFlatUoms: () => ({
    data: unitsRead.failed
      ? undefined
      : [
          {
            id: "u1",
            symbol: "pcs",
            name: "Piece",
            category_id: "c2",
            factor: 1,
          },
        ],
    isError: unitsRead.failed,
  }),
  useUoms: () => ({ data: [], isLoading: false }),
}));

vi.mock("@/modules/shared/components/UomSelect", () => ({
  UomSelect: (props: { convertibleHint?: string }) => (
    <div data-testid="uom-select" data-hint={props.convertibleHint ?? ""} />
  ),
}));

vi.mock("@/modules/maker/components/ProductSearchInput", () => ({
  ProductSearchInput: ({
    onSelect,
  }: {
    onSelect: (p: {
      product_template_id: string;
      name: string;
      uom_id: string;
      uom_symbol: string | null;
    }) => void;
  }) => (
    <button
      type="button"
      onClick={() =>
        // The picked product carries its own unit — the ingredient form
        // follows it, and a product with no unit leaves the picker empty
        // rather than pre-filling a unit the guard may refuse.
        onSelect({
          product_template_id: "tpl-1",
          name: "The recipe itself",
          uom_id: "u1",
          uom_symbol: "pcs",
        })
      }
    >
      pick a product
    </button>
  ),
}));

function rejectWith(status: number, message: string) {
  vi.mocked(recipeApi.addBomLine).mockRejectedValue({
    isAxiosError: true,
    response: {
      status,
      data: { detail: { code: "VALIDATION_ERROR", message } },
    },
  });
}

async function pickAndAdd(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByText("pick a product"));
  await user.click(screen.getByTestId("maker-composition-add-line"));
}

describe("RecipeIngredientForm", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    unitsRead.failed = false;
  });

  it("names the stock unit in the picker's hint once the units are known", async () => {
    const user = userEvent.setup();
    render(<RecipeIngredientForm recipeId="r1" outputTemplateId="tpl-out" />);
    await user.click(screen.getByText("pick a product"));

    expect(screen.getByTestId("uom-convertible-hint").textContent).toMatch(
      /pcs/,
    );
    // Said at the full row width, not inside the picker's narrow column.
    expect(screen.getByTestId("uom-convertible-hint").className).toContain(
      "sm:basis-full",
    );
    expect(screen.getByTestId("uom-select").getAttribute("data-hint")).toBe("");
  });

  it("drops the hint rather than naming a unit it cannot read when the units failed", async () => {
    // The hint reads "convertible into {{unit}}"; without the catalogue the
    // unit came out empty and the sentence broke in the middle.
    unitsRead.failed = true;
    const user = userEvent.setup();
    render(<RecipeIngredientForm recipeId="r1" outputTemplateId="tpl-out" />);
    await user.click(screen.getByText("pick a product"));

    expect(screen.queryByTestId("uom-convertible-hint")).toBeNull();
  });

  it("keeps the backend's refusal on screen, next to the line it is about", async () => {
    rejectWith(
      400,
      "A BOM line cannot reference the product itself — it would make the product an ingredient of its own BOM.",
    );
    const user = userEvent.setup();
    render(<RecipeIngredientForm recipeId="r-1" outputTemplateId="tpl-out" />);

    await pickAndAdd(user);

    await waitFor(() =>
      expect(screen.getByTestId("maker-composition-error")).toHaveTextContent(
        "A BOM line cannot reference the product itself — it would make the product an ingredient of its own BOM.",
      ),
    );
    expect(screen.getByRole("alert")).toBeInTheDocument();
  });

  it("names a duplicate in the app's own words", async () => {
    rejectWith(409, "already there");
    const user = userEvent.setup();
    render(<RecipeIngredientForm recipeId="r-1" outputTemplateId="tpl-out" />);

    await pickAndAdd(user);

    await waitFor(() =>
      expect(screen.getByTestId("maker-composition-error")).toBeInTheDocument(),
    );
    expect(screen.getByTestId("maker-composition-error")).not.toHaveTextContent(
      "already there",
    );
  });

  it("clears the refusal once a different product is picked", async () => {
    rejectWith(
      400,
      "A BOM line cannot reference the product itself — it would make the product an ingredient of its own BOM.",
    );
    const user = userEvent.setup();
    render(<RecipeIngredientForm recipeId="r-1" outputTemplateId="tpl-out" />);

    await pickAndAdd(user);
    await waitFor(() =>
      expect(screen.getByTestId("maker-composition-error")).toBeInTheDocument(),
    );

    await user.click(screen.getByTestId("maker-composition-child-clear"));

    expect(screen.queryByTestId("maker-composition-error")).toBeNull();
  });
});
