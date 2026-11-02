import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import IngredientRow from "./IngredientRow";
import { signInWith, signOut } from "@/test/auth";
import type { IngredientAvailability } from "@/modules/recipes/types/core";

// Linking and the exclusion toggle are `recipes:write` on the API; the row
// asks `useCanWrite` before offering them.
beforeEach(() => signInWith(["recipes:read", "recipes:write"]));
afterEach(() => {
  signOut();
  exclusionsRead.failed = false;
  exclusionsRead.refetch.mockClear();
});

const exclusionsRead = vi.hoisted(() => ({
  failed: false,
  refetch: vi.fn(),
}));
vi.mock("../hooks/useMealPlans", () => ({
  useShoppingExclusions: () => ({
    data: exclusionsRead.failed ? undefined : [],
    isLoading: false,
    isError: exclusionsRead.failed,
    refetch: exclusionsRead.refetch,
  }),
  useCreateShoppingExclusion: () => ({ mutate: vi.fn(), isPending: false }),
  useDeleteShoppingExclusion: () => ({ mutate: vi.fn(), isPending: false }),
}));

vi.mock("../hooks/useRecipes", () => ({
  useLinkIngredientTemplate: () => ({
    mutateAsync: vi.fn(),
    isPending: false,
  }),
}));

const base: IngredientAvailability = {
  ingredient_id: "i1",
  name: "Jajka",
  required_quantity: 2,
  required_uom: "szt",
  status: "available",
  match_type: "exact",
  is_linked: true,
  is_spice: false,
  excluded: false,
  quantities_comparable: true,
  available_quantity: null,
  available_uom: null,
  best_item: null,
  alternative_items: [],
  display_text: null,
  original_quantity: null,
  original_unit_text: null,
};

describe("IngredientRow — quantity display", () => {
  it("shows correct quantity for whole number countable", () => {
    render(
      <IngredientRow
        ingredient={{ ...base, required_quantity: 2, required_uom: "szt" }}
      />,
    );
    // Amount and unit are one phrase, not two columns.
    expect(screen.getByText("2 szt")).toBeInTheDocument();
  });

  it("shows vulgar fraction for fractional values", () => {
    render(
      <IngredientRow
        ingredient={{ ...base, required_quantity: 2.5, required_uom: "szt" }}
      />,
    );
    expect(screen.getByText("2½ szt")).toBeInTheDocument();
  });

  it("shows amber color for fractional countable", () => {
    render(
      <IngredientRow
        ingredient={{ ...base, required_quantity: 2.5, required_uom: "szt" }}
      />,
    );
    const qtyEl = screen.getByText(/^2½/);
    expect(qtyEl).toHaveClass("text-amber-600");
    expect(qtyEl).toHaveClass("font-medium");
  });

  it('shows amber for fractional "pcs" UOM', () => {
    render(
      <IngredientRow
        ingredient={{ ...base, required_quantity: 1.5, required_uom: "pcs" }}
      />,
    );
    const qtyEl = screen.getByText(/^1½/);
    expect(qtyEl).toHaveClass("text-amber-600");
  });

  it('shows amber for fractional "jajko" UOM', () => {
    render(
      <IngredientRow
        ingredient={{ ...base, required_quantity: 2.5, required_uom: "jajko" }}
      />,
    );
    const qtyEl = screen.getByText(/^2½/);
    expect(qtyEl).toHaveClass("text-amber-600");
  });

  it("does NOT show amber for non-countable fractional (0.5 kg)", () => {
    render(
      <IngredientRow
        ingredient={{ ...base, required_quantity: 0.5, required_uom: "kg" }}
      />,
    );
    const qtyEl = screen.getByText(/^½/);
    expect(qtyEl).not.toHaveClass("text-amber-600");
    expect(qtyEl).toHaveClass("text-on-muted");
  });

  it("fractional countable span has tooltip title", () => {
    render(
      <IngredientRow
        ingredient={{ ...base, required_quantity: 2.5, required_uom: "szt" }}
      />,
    );
    const qtyEl = screen.getByText(/^2½/);
    expect(qtyEl).toHaveAttribute("title");
    expect(qtyEl.getAttribute("title")).not.toBe("");
  });

  it("whole countable does NOT have tooltip title", () => {
    render(
      <IngredientRow
        ingredient={{ ...base, required_quantity: 3, required_uom: "szt" }}
      />,
    );
    const qtyEl = screen.getByText(/^3/);
    expect(qtyEl).not.toHaveAttribute("title");
  });

  it("says what the unit's step rounded the requirement up from", () => {
    // A recipe that says ½ pcs is asked as 1 pcs — deliberate, part of a
    // carton is a carton — but the card showed only the 1, and the person
    // who typed the half could not tell whether it had saved.
    render(
      <IngredientRow
        ingredient={{
          ...base,
          required_quantity: 1,
          required_uom: "pcs",
          required_quantity_unrounded: 0.5,
        }}
      />,
    );
    expect(screen.getByText(/^1 pcs/)).toBeInTheDocument();
    const note = screen.getByTestId("rounded-up");
    expect(note).toHaveTextContent("½");
    expect(note).toHaveTextContent("pcs");
  });

  it("keeps the fractional hint for a piece the step rounded", () => {
    render(
      <IngredientRow
        ingredient={{
          ...base,
          required_quantity: 1,
          required_uom: "pcs",
          required_quantity_unrounded: 0.5,
        }}
      />,
    );
    expect(screen.getByText(/^1 pcs/)).toHaveClass("text-amber-600");
  });

  it("does not explain a rounding the displayed number already hides", () => {
    // A scaled third restates as ⅓ before and after the step, so there is
    // nothing on the row the reader can see to explain.
    render(
      <IngredientRow
        ingredient={{
          ...base,
          required_quantity: 3.334,
          required_uom: "g",
          required_quantity_unrounded: 3.3333,
        }}
      />,
    );
    expect(screen.queryByTestId("rounded-up")).not.toBeInTheDocument();
  });

  it("shows no rounding note for a requirement already on its step", () => {
    render(
      <IngredientRow
        ingredient={{
          ...base,
          required_quantity: 2,
          required_uom: "pcs",
          required_quantity_unrounded: null,
        }}
      />,
    );
    expect(screen.queryByTestId("rounded-up")).not.toBeInTheDocument();
  });
});

describe("IngredientRow — FEFO warning", () => {
  it("shows FEFO warning when best_item has fefo_days_left and expiry_date", () => {
    render(
      <IngredientRow
        ingredient={{
          ...base,
          best_item: {
            item_id: "x",
            available_quantity: 3,
            uom_symbol: null,
            location: null,
            expiry_date: "2026-03-15",
            fefo_days_left: 8,
            expired: false,
          },
        }}
      />,
    );
    expect(
      screen.getByText(/2026|mar|15|Short shelf life|Krótki/i),
    ).toBeInTheDocument();
  });

  it("does NOT show FEFO warning when fefo_days_left is null", () => {
    render(
      <IngredientRow
        ingredient={{
          ...base,
          best_item: {
            item_id: "x",
            available_quantity: 3,
            uom_symbol: null,
            location: null,
            expiry_date: "2026-03-15",
            fefo_days_left: null,
            expired: false,
          },
        }}
      />,
    );
    expect(
      screen.queryByText(/Short shelf life|Krótki/i),
    ).not.toBeInTheDocument();
  });
});

describe("IngredientRow — past its date", () => {
  it("names a pack past its date as expired, not as short of shelf life", () => {
    // The only pack is on the shelf and went off two days ago: the row keeps
    // saying where it is, and says what it is.
    render(
      <IngredientRow
        ingredient={{
          ...base,
          status: "missing",
          best_item: {
            item_id: "x",
            available_quantity: 500,
            uom_symbol: "g",
            location: "Fridge A",
            expiry_date: "2026-03-15",
            fefo_days_left: -2,
            expired: true,
          },
        }}
      />,
    );
    expect(screen.getByTestId("expired")).toHaveTextContent(
      /Expired|Po terminie/i,
    );
    expect(
      screen.queryByText(/Short shelf life|Krótki/i),
    ).not.toBeInTheDocument();
    expect(screen.getByText("Fridge A")).toBeInTheDocument();
  });
});

describe("IngredientRow — status dot", () => {
  it("names the status dot so colour is not its only carrier", () => {
    render(<IngredientRow ingredient={{ ...base, status: "available" }} />);
    // Success speaks through the `success` ramp, not `accent`, and the
    // dot is announced rather than relying on `title` alone.
    const dot = screen.getByRole("img", { name: /available/i });
    expect(dot).toHaveClass("bg-success-400");
  });

  it("renders a red dot for missing status", () => {
    const { container } = render(
      <IngredientRow
        ingredient={{ ...base, status: "missing", is_linked: false }}
      />,
    );
    const dot = container.querySelector(".bg-red-400");
    expect(dot).toBeInTheDocument();
  });
});

describe("IngredientRow — storage location", () => {
  it("shows location when best_item has location", () => {
    render(
      <IngredientRow
        ingredient={{
          ...base,
          best_item: {
            item_id: "x",
            available_quantity: 3,
            uom_symbol: null,
            location: "Lodówka > Półka 1",
            expiry_date: null,
            fefo_days_left: null,
            expired: false,
          },
        }}
      />,
    );
    expect(screen.getByText("Lodówka > Półka 1")).toBeInTheDocument();
  });

  it("does not show location when best_item is null", () => {
    render(<IngredientRow ingredient={{ ...base, best_item: null }} />);
    expect(screen.queryByText(/Lodówka/)).not.toBeInTheDocument();
  });
});

describe("IngredientRow — link to product", () => {
  it("shows link button for unknown-status ingredients with recipeId", () => {
    render(
      <IngredientRow
        ingredient={{ ...base, status: "unknown", is_linked: false }}
        recipeId="r1"
      />,
    );
    expect(screen.getByText("Link to product")).toBeInTheDocument();
  });

  it("does not show link button without recipeId", () => {
    render(
      <IngredientRow
        ingredient={{ ...base, status: "unknown", is_linked: false }}
      />,
    );
    expect(screen.queryByText("Link to product")).not.toBeInTheDocument();
  });

  it("offers linking for missing ingredients too, with quieter weight", () => {
    // The automatic answer can be wrong or absent; linking by hand stays a
    // way out, but it is no longer the only thing the row can say.
    render(
      <IngredientRow
        ingredient={{ ...base, status: "missing", is_linked: false }}
        recipeId="r1"
      />,
    );
    const button = screen.getByRole("button", { name: "Link to product" });
    expect(button).toHaveClass("text-on-muted");
    expect(button).not.toHaveClass("text-primary-600");
  });

  it("does not offer linking when the ingredient already points at a product", () => {
    // It used to follow the stock answer, so the control sat on a linked row
    // that was merely short of stock — where it could change nothing — and
    // was absent from a row matched only by name, where it is the fix.
    render(
      <IngredientRow
        ingredient={{ ...base, status: "insufficient", is_linked: true }}
        recipeId="r1"
      />,
    );
    expect(screen.queryByText("Link to product")).not.toBeInTheDocument();
  });

  it("offers linking on a row matched only by its name", () => {
    render(
      <IngredientRow
        ingredient={{
          ...base,
          status: "available_approx",
          match_type: "fuzzy",
          is_linked: false,
        }}
        recipeId="r1"
      />,
    );
    expect(screen.getByText("Link to product")).toBeInTheDocument();
  });

  it("hides linking and the exclusion toggle from a reader", () => {
    // Both write through `recipes:write`; a read-only account was offered
    // them and met the refusal only after choosing.
    signOut();
    render(
      <IngredientRow
        ingredient={{ ...base, status: "unknown", is_linked: false }}
        recipeId="r1"
      />,
    );
    expect(screen.queryByText("Link to product")).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /exclude from shopping lists/i }),
    ).not.toBeInTheDocument();
  });
});

describe("IngredientRow — not enough is not none", () => {
  // 492 ml of the 500 ml a recipe wants used to read exactly like an empty
  // fridge: the same red dot, the same word, and no number anywhere. People
  // went shopping for milk they had, or gave up on cooking five portions of
  // six.
  const short = {
    ...base,
    name: "Mleko",
    required_quantity: 500,
    required_uom: "ml",
    status: "insufficient" as const,
    available_quantity: 492,
    available_uom: "ml",
  };

  it("says how much there is against how much is needed", () => {
    render(<IngredientRow ingredient={short} />);
    const note = screen.getByTestId("short-of");
    expect(note.textContent).toContain("492");
    expect(note.textContent).toContain("500");
  });

  it("is a different answer from an empty shelf", () => {
    const { unmount } = render(<IngredientRow ingredient={short} />);
    expect(screen.getByRole("img", { name: "Not enough" })).toBeInTheDocument();
    unmount();

    render(
      <IngredientRow
        ingredient={{ ...base, status: "missing", is_linked: false }}
      />,
    );
    expect(screen.getByRole("img", { name: "Missing" })).toBeInTheDocument();
    expect(screen.queryByTestId("short-of")).not.toBeInTheDocument();
  });
});

describe("IngredientRow — measures that cannot be compared", () => {
  const incomparable: IngredientAvailability = {
    ...base,
    name: "Ciecierzyca z puszki",
    required_quantity: 400,
    required_uom: "g",
    status: "available_approx",
    match_type: "fuzzy",
    quantities_comparable: false,
    available_quantity: 7,
    available_uom: "pcs",
  };

  it("shows both readings instead of a verdict", () => {
    render(<IngredientRow ingredient={incomparable} />);
    const note = screen.getByTestId("not-comparable");
    expect(note.textContent).toContain("7");
    expect(note.textContent).toContain("400");
  });

  it("says why in words, not in a hover", () => {
    // The explanation used to live in a `title` attribute, which on a phone
    // in a kitchen is nowhere.
    render(<IngredientRow ingredient={incomparable} />);
    const note = screen.getByTestId("not-comparable");
    expect(note.textContent).toContain("Cannot compare");
    expect(note).not.toHaveAttribute("title");
  });

  it("names the field the product card really has as the way out", () => {
    // The product card offers "Weight / volume per piece"; a kg-stocked
    // product has no pack, so the old "pack size" pointed at nothing.
    render(<IngredientRow ingredient={{ ...incomparable, best_item: null }} />);
    expect(screen.getByTestId("not-comparable").textContent).toContain(
      "weight or volume per piece",
    );
  });

  it("marks the row as uncomparable rather than in stock", () => {
    render(<IngredientRow ingredient={incomparable} />);
    expect(
      screen.getByRole("img", { name: "Cannot be compared" }),
    ).toBeInTheDocument();
  });

  it("stays silent when the two measures do meet", () => {
    render(
      <IngredientRow
        ingredient={{ ...incomparable, quantities_comparable: true }}
      />,
    );
    expect(screen.queryByTestId("not-comparable")).not.toBeInTheDocument();
  });
});

describe("IngredientRow — mobile link button", () => {
  // Real geometry (container width > 0 at 390 px) is asserted by the
  // Playwright spec; jsdom has no layout, so here we pin the CSS contract
  // that produces it: truncate on the name container + icon-only button.
  it("truncates the name container so it clips instead of overflowing", () => {
    render(
      <IngredientRow
        ingredient={{ ...base, status: "unknown", is_linked: false }}
        recipeId="r1"
      />,
    );
    const nameContainer = screen.getByTestId("ingredient-name");
    expect(nameContainer).toHaveClass("flex-1", "min-w-0");
    // The clipping sits on the line itself, so the meta row below it — the
    // location, the expiry warning — still wraps rather than being cut off.
    expect(nameContainer.firstElementChild).toHaveClass("truncate");
  });

  it("renders an icon-only link button below sm with an accessible label", () => {
    render(
      <IngredientRow
        ingredient={{ ...base, status: "unknown", is_linked: false }}
        recipeId="r1"
      />,
    );
    const button = screen.getByRole("button", {
      name: "Link to product",
    });
    expect(button).toHaveAttribute("aria-label", "Link to product");
    const label = button.querySelector("span");
    expect(label).toHaveClass("hidden", "sm:inline");
  });
});

describe("IngredientRow — one reading for both kinds of ingredient", () => {
  const imported = {
    ...base,
    name: "słodki sos chili",
    display_text: "słodki sos chili - 4 łyżki",
    required_quantity: 60,
    required_uom: "ml",
  };
  const byHand = {
    ...base,
    name: "ryż",
    required_quantity: 200,
    required_uom: "g",
  };

  it("puts the name first and the measure after it, whichever it is", () => {
    const { rerender } = render(<IngredientRow ingredient={imported} />);
    let line = screen.getByTestId("ingredient-name");
    expect(line.textContent).toBe("słodki sos chili - 4 łyżki (60 ml)");

    rerender(<IngredientRow ingredient={byHand} />);
    line = screen.getByTestId("ingredient-name");
    expect(line.textContent).toBe("ryż 200 g");
  });

  it("keeps the recipe's own wording where the import supplied it", () => {
    render(<IngredientRow ingredient={imported} />);

    expect(screen.getByText("słodki sos chili - 4 łyżki")).toBeInTheDocument();
  });

  it("flags a fractional count on an imported line too", () => {
    // The old imported branch had no amber and no hint: half an egg read as
    // an ordinary amount as long as the recipe came from a URL.
    render(
      <IngredientRow
        ingredient={{
          ...imported,
          required_quantity: 2.5,
          required_uom: "szt",
        }}
      />,
    );

    expect(screen.getByText("(2½ szt)")).toHaveClass("text-amber-600");
  });
});

describe("IngredientRow — the exclusions did not load", () => {
  it("offers a retry in place of a toggle that would claim nothing is excluded", () => {
    exclusionsRead.failed = true;
    render(<IngredientRow ingredient={base} />);

    expect(
      screen.queryByRole("button", { name: /exclude from shopping lists/i }),
    ).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /try again/i }));
    expect(exclusionsRead.refetch).toHaveBeenCalledTimes(1);
  });
});
