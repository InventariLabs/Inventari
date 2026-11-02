import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import type { ReactElement } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import CookingMode, { buildSteps, type CookingModeProps } from "./CookingMode";
import type { RecipeIngredient } from "@/modules/recipes/types/core";

// Finishing a cook records its own history entry, so mounting the mode
// mounts a mutation — which needs a client to live in.
function withClient(ui: ReactElement) {
  return (
    <QueryClientProvider client={new QueryClient()}>{ui}</QueryClientProvider>
  );
}

function ingredient(overrides: Partial<RecipeIngredient>): RecipeIngredient {
  return {
    id: "i1",
    recipe_id: "r1",
    name: "Flour",
    template_id: null,
    ingredient_group_name: null,
    quantity: "2",
    uom_id: null,
    uom_symbol: "kg",
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
    ...overrides,
  };
}

function baseProps(): Omit<CookingModeProps, "ingredients"> {
  return {
    recipeId: "r1",
    recipeName: "Test recipe",
    instructions: "1. Boil water\n2. Fry onions",
    onClose: vi.fn(),
  };
}

function renderCookingMode(instructions: string) {
  return render(
    withClient(
      <CookingMode
        recipeId="r1"
        recipeName="Test recipe"
        instructions={instructions}
        onClose={vi.fn()}
      />,
    ),
  );
}

describe("buildSteps — inline numbered steps", () => {
  it("splits inline '1. ... 2. ...' on one line into separate steps", () => {
    const steps = buildSteps(
      "1. Boil water. 2. Fry onions. 3. Add pasta. 4. Serve",
    );
    expect(steps).toHaveLength(4);
    expect(steps.map((s) => s.stepNumber)).toEqual([1, 2, 3, 4]);
    expect(steps[0].body).toContain("Boil water");
    expect(steps[1].body).toContain("Fry onions");
    expect(steps[3].body).toContain("Serve");
  });

  it("splits inline '1) ... 2) ...' style", () => {
    const steps = buildSteps("1) Heat the pan. 2) Add oil.");
    expect(steps).toHaveLength(2);
    expect(steps[1].body).toContain("Add oil");
  });

  it("does not split non-sequential numbers", () => {
    const steps = buildSteps("1. Boil water. 3. Fry onions.");
    expect(steps).toHaveLength(1);
  });

  it("does not treat mid-sentence numbers as step markers", () => {
    const steps = buildSteps("Bake at 200 degrees. 2. Serve hot.");
    expect(steps).toHaveLength(1);
  });

  it("still splits newline-numbered steps", () => {
    const steps = buildSteps("1. Boil water\n2. Fry onions");
    expect(steps.length).toBeGreaterThanOrEqual(2);
  });

  it("keeps plain text as a single step", () => {
    const steps = buildSteps("Mix everything and serve warm.");
    expect(steps).toHaveLength(1);
  });

  it("does not treat markdown headings as steps", () => {
    const steps = buildSteps("## Przygotowanie\n1. Krok\n2. Krok");
    expect(steps).toHaveLength(2);
    expect(steps.map((s) => s.stepNumber)).toEqual([1, 2]);
    expect(steps[0].title).toBe("Krok");
    expect(steps[1].title).toBe("Krok");
  });

  it("skips a heading between numbered steps", () => {
    const steps = buildSteps("1. Krok\n## Gotowanie\n2. Krok");
    expect(steps).toHaveLength(2);
    expect(steps.map((s) => s.stepNumber)).toEqual([1, 2]);
  });
});

/**
 * The recipe form promises "one step per line (or numbering: 1. 2. 3.)".
 * Three ways of writing the same instructions, one contract: what the form
 * asked for is what the reader gets.
 */
describe("buildSteps — one step per line", () => {
  it("splits plain lines, as the form's hint promises", () => {
    const steps = buildSteps(
      "Wymieszaj składniki\nOdstaw na 12 godzin\nPiecz 40 minut",
    );
    expect(steps).toHaveLength(3);
    expect(steps[1].body).toBe("Odstaw na 12 godzin");
  });

  it("lets a blank line group lines into one step", () => {
    // A blank line is the author grouping deliberately; that wins over the
    // per-line rule, so a wrapped paragraph stays a single step.
    const steps = buildSteps(
      "Wymieszaj składniki\naż będą gładkie\n\nPiecz 40 minut",
    );
    expect(steps).toHaveLength(2);
    expect(steps[0].body).toContain("aż będą gładkie");
  });

  it("still prefers explicit numbering over line breaks", () => {
    const steps = buildSteps("1. Wymieszaj\n2. Odstaw\n3. Piecz");
    expect(steps).toHaveLength(3);
    expect(steps.map((s) => s.stepNumber)).toEqual([1, 2, 3]);
  });
});

describe("CookingMode ingredients panel", () => {
  it("hides the ingredient list by default and expands on toggle", () => {
    render(
      withClient(
        <CookingMode
          {...baseProps()}
          ingredients={[
            ingredient({}),
            ingredient({
              id: "i2",
              name: "Milk",
              quantity: "0.5",
              uom_symbol: "l",
            }),
          ]}
        />,
      ),
    );
    expect(screen.queryByText("Flour")).not.toBeInTheDocument();
    expect(screen.queryByText("Milk")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /ingredients/i }));
    expect(screen.getByText("Flour")).toBeInTheDocument();
    expect(screen.getByText("Milk")).toBeInTheDocument();
    expect(screen.getByText(/2\s*kg/)).toBeInTheDocument();
    expect(screen.getByText(/0\.5\s*l/)).toBeInTheDocument();
  });

  it("does not render the panel without ingredients", () => {
    render(withClient(<CookingMode {...baseProps()} />));
    expect(
      screen.queryByRole("button", { name: /ingredients/i }),
    ).not.toBeInTheDocument();
  });

  it("renders string-serialized Decimal quantities without crashing", () => {
    // Live API sends quantity as a string ("2.5"); unit mocks used numbers.
    render(
      withClient(
        <CookingMode
          {...baseProps()}
          ingredients={[ingredient({ quantity: "2.5" })]}
        />,
      ),
    );
    fireEvent.click(screen.getByRole("button", { name: /ingredients/i }));
    expect(screen.getByText(/2\.5\s*kg/)).toBeInTheDocument();
  });
});

describe("CookingMode timer detection — Polish declined forms", () => {
  it("detects 'minucie' (locative)", () => {
    renderCookingMode("Smaż po 1 minucie, aż będzie złote.");
    expect(screen.getByText(/Timer — 1:00/)).toBeInTheDocument();
  });

  it("detects 'minuty' (genitive)", () => {
    renderCookingMode("Piecz przez 2 minuty, aż się zrumieni.");
    expect(screen.getByText(/Timer — 2:00/)).toBeInTheDocument();
  });

  it("detects 'minutach' (locative plural)", () => {
    renderCookingMode("Gotuj po 5 minutach na parze.");
    expect(screen.getByText(/Timer — 5:00/)).toBeInTheDocument();
  });

  it("detects 'godzinę' (accusative)", () => {
    renderCookingMode("Dusić przez 1 godzinę pod przykryciem.");
    expect(screen.getByText(/Timer — 1:00:00/)).toBeInTheDocument();
  });

  it("still detects English forms", () => {
    renderCookingMode("Simmer for 3 minutes and 30 seconds.");
    expect(screen.getByText(/Timer — 3:00/)).toBeInTheDocument();
  });

  it("still detects range timers ('2-3 minuty')", () => {
    renderCookingMode("Smaż przez 2-3 minuty z każdej strony.");
    expect(screen.getByText(/Timer — 2:00/)).toBeInTheDocument();
  });
});

describe("CookingMode dialog semantics", () => {
  it("exposes the overlay as a modal dialog named after the recipe", () => {
    renderCookingMode("1. Boil water\n2. Fry onions");
    const dialog = screen.getByRole("dialog", { name: "Test recipe" });
    expect(dialog).toHaveAttribute("aria-modal", "true");
  });

  // The card is focusable, clickable and handles Enter/Space, so it announces
  // itself as a button. `group` is a non-interactive role and told a screen
  // reader the opposite of what the element does.
  it("labels every step card and announces it as interactive", () => {
    renderCookingMode("1. Boil water\n2. Fry onions");
    expect(screen.getByRole("button", { name: "Step 1" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Step 2" })).toBeInTheDocument();
  });

  it("marks the active step for assistive technology", () => {
    renderCookingMode("1. Boil water\n2. Fry onions");
    expect(screen.getByRole("button", { name: "Step 1" })).toHaveAttribute(
      "aria-current",
      "step",
    );
    expect(screen.getByRole("button", { name: "Step 2" })).not.toHaveAttribute(
      "aria-current",
    );
  });

  it("activates a step card from the keyboard", () => {
    const { unmount } = renderCookingMode("1. Boil water\n2. Fry onions");
    const step2 = screen.getByRole("button", { name: "Step 2" });
    fireEvent.keyDown(step2, { key: "Enter" });
    expect(step2).toHaveAttribute("aria-current", "step");

    unmount();
    renderCookingMode("1. Boil water\n2. Fry onions");
    const step2Again = screen.getByRole("button", { name: "Step 2" });
    fireEvent.keyDown(step2Again, { key: " " });
    expect(step2Again).toHaveAttribute("aria-current", "step");
  });
});

describe("CookingMode kitchen ergonomics", () => {
  it("renders the active step heading large enough to read from a distance", () => {
    renderCookingMode("1. Boil water\n2. Fry onions");
    const activeHeading = screen.getByText("Boil water");
    expect(activeHeading).toHaveClass("text-2xl");
  });

  it("renders inline-numbered step bodies large in the active step", () => {
    renderCookingMode("1. Boil water. 2. Fry onions.");
    const activeBody = screen.getByText("Boil water");
    expect(activeBody).toHaveClass("text-2xl");
  });

  it("renders paragraph-split step bodies large in the active step", () => {
    renderCookingMode("Mix everything.\n\nServe warm.");
    const activeBody = screen.getByText("Mix everything.");
    expect(activeBody).toHaveClass("text-2xl");
  });

  it("renders a single-paragraph instruction large in the active step", () => {
    renderCookingMode("Mix everything and serve warm.");
    const activeBody = screen.getByText("Mix everything and serve warm.");
    expect(activeBody).toHaveClass("text-2xl");
  });

  it("gives the navigation buttons at least 48px height", () => {
    renderCookingMode("1. Boil water\n2. Fry onions");
    const next = screen.getByRole("button", { name: /next/i });
    expect(next).toHaveClass("h-12");
  });
});
