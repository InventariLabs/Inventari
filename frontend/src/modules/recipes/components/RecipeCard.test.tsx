import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { RecipeCard } from "./RecipeCard";
import en from "@/modules/recipes/i18n/en.json";
import type { TFunction } from "i18next";
import type { RecipeList } from "@/modules/recipes/types/core";

const t = ((key: string) => {
  const path = key.replace("recipes:", "").split(".");
  let value: unknown = en;
  for (const part of path) {
    if (value && typeof value === "object" && part in value) {
      value = (value as Record<string, unknown>)[part];
    } else {
      return key;
    }
  }
  return typeof value === "string" ? value : key;
}) as unknown as TFunction;

const makeRecipe = (overrides: Partial<RecipeList> = {}): RecipeList => ({
  id: "r1",
  name: "Recipe 1",
  description: null,
  servings: 2,
  prep_time_minutes: null,
  image_url: null,
  tags: null,
  is_favorite: false,
  created_at: "2026-01-01T00:00:00Z",
  source_url: null,
  ingredients_total: 0,
  ingredients_linked: 0,
  ingredients_available: 0,
  ingredients_incomparable: 0,
  missing_names: [],
  ...overrides,
});

const baseProps = {
  selectedTags: [] as string[],
  tagColorMap: new Map<string, string | null>(),
  selectionMode: false,
  selected: false,
  dragEnabled: false,
  onToggleSelect: vi.fn(),
  onToggleFavorite: vi.fn(),
  onEdit: vi.fn(),
  onDelete: vi.fn(),
  onDuplicate: vi.fn(),
  onTagClick: vi.fn(),
  linkTo: "/recipes/r1",
  t,
};

describe("RecipeCard tag keyboard access", () => {
  it("activates a tag with Enter and with Space", async () => {
    const user = userEvent.setup();
    const onTagClick = vi.fn();
    render(
      <MemoryRouter>
        <RecipeCard
          {...baseProps}
          recipe={makeRecipe({ tags: ["vegan"] })}
          onTagClick={onTagClick}
        />
      </MemoryRouter>,
    );
    const tag = screen.getByRole("button", { name: "vegan" });

    // A `<Badge onClick>` renders a div: no focus, no keyboard, no role. The
    // native button gets Enter and Space from the platform — user-event
    // reproduces that activation behaviour, so no click is fired by hand here
    // (a hand-fired click passes even when keyboard activation is broken).
    tag.focus();
    expect(tag).toHaveFocus();
    await user.keyboard("{Enter}");
    expect(onTagClick).toHaveBeenCalledWith("vegan");

    onTagClick.mockClear();
    await user.keyboard(" ");
    expect(onTagClick).toHaveBeenCalledWith("vegan");
  });

  it("reports its filter state through aria-pressed", () => {
    const { rerender } = render(
      <MemoryRouter>
        <RecipeCard {...baseProps} recipe={makeRecipe({ tags: ["vegan"] })} />
      </MemoryRouter>,
    );
    expect(screen.getByRole("button", { name: "vegan" })).toHaveAttribute(
      "aria-pressed",
      "false",
    );

    rerender(
      <MemoryRouter>
        <RecipeCard
          {...baseProps}
          recipe={makeRecipe({ tags: ["vegan"] })}
          selectedTags={["vegan"]}
        />
      </MemoryRouter>,
    );
    expect(screen.getByRole("button", { name: "vegan" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
  });
});

describe("RecipeCard tag pill", () => {
  it("carries the selected state on the canonical pill, not on a ramp step", () => {
    render(
      <MemoryRouter>
        <RecipeCard
          {...baseProps}
          recipe={makeRecipe({ tags: ["vegan"] })}
          selectedTags={["vegan"]}
        />
      </MemoryRouter>,
    );
    const pill = screen.getByText("vegan");

    expect(pill.className).toContain("bg-primary-50");
    expect(pill.className).toContain("border-primary-500");
    // Weight is no longer one of the signals: a 12px pill does not carry a
    // title weight (§1.2), and the base already sets `font-medium`, so
    // repeating it said nothing about being selected. Colour and border do.
    expect(pill.className).not.toContain("font-semibold");
    expect(pill.className).not.toContain("text-primary-700");
    expect(pill.className).not.toContain("dark:");
  });
});

describe("RecipeCard — image rendering", () => {
  it("renders the recipe image when image_url is set", () => {
    render(
      <MemoryRouter>
        <RecipeCard
          {...baseProps}
          recipe={makeRecipe({
            image_url: "https://example.com/photo.jpg",
          })}
        />
      </MemoryRouter>,
    );
    const img = screen.getByRole("img");
    expect(img).toHaveAttribute("src", "https://example.com/photo.jpg");
    expect(img).toHaveAttribute("alt", "Recipe 1");
    expect(
      screen.queryByTestId("recipe-image-placeholder"),
    ).not.toBeInTheDocument();
  });

  it("renders a neutral placeholder instead of the gradient bar when there is no image", () => {
    const { container } = render(
      <MemoryRouter>
        <RecipeCard {...baseProps} recipe={makeRecipe({ image_url: null })} />
      </MemoryRouter>,
    );
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
    expect(screen.getByTestId("recipe-image-placeholder")).toBeInTheDocument();
    // Regression: the decorative gradient bar must not be rendered at all.
    expect(container.querySelector(".from-primary-400")).toBeNull();
  });

  it("collapses the missing-image placeholder to a slim strip instead of a full media box", () => {
    render(
      <MemoryRouter>
        <RecipeCard {...baseProps} recipe={makeRecipe({ image_url: null })} />
      </MemoryRouter>,
    );
    const placeholder = screen.getByTestId("recipe-image-placeholder");
    expect(placeholder).toHaveClass("h-12");
    expect(placeholder).not.toHaveClass("aspect-video");
  });

  it("renders card tags as lowercase pills matching the filter chips", () => {
    render(
      <MemoryRouter>
        <RecipeCard {...baseProps} recipe={makeRecipe({ tags: ["Italian"] })} />
      </MemoryRouter>,
    );
    // `normal-case` used to be here to cancel Badge's uppercase default. The
    // tag is a Button now, which has no case transform to undo.
    const tag = screen.getByRole("button", { name: "Italian" });
    expect(tag).toHaveClass("rounded-full");
    expect(tag).not.toHaveClass("uppercase");
  });
  it("puts the media on the card edge instead of inside its padding", () => {
    render(
      <MemoryRouter>
        <RecipeCard {...baseProps} recipe={makeRecipe({ image_url: null })} />
      </MemoryRouter>,
    );
    const card = screen.getByTestId("recipe-card");
    // The card owns no padding of its own; the content layer below the media
    // carries it. Otherwise the placeholder is inset and its border-b stops
    // short of both edges.
    expect(card).toHaveClass("p-0");
    expect(card).not.toHaveClass("p-6");
    const placeholder = screen.getByTestId("recipe-image-placeholder");
    expect(placeholder.parentElement?.className ?? "").not.toMatch(
      /\bp[xl]?-[1-9]/,
    );
  });

  it("reserves a place for the action bar instead of laying it over the tags", () => {
    render(
      <MemoryRouter>
        <RecipeCard {...baseProps} recipe={makeRecipe({ tags: ["quick"] })} />
      </MemoryRouter>,
    );
    const bar = screen.getByTestId("recipe-delete-btn").parentElement!;
    expect(bar.className).not.toContain("absolute");
    // The link must be a flex child that grows, or `mt-auto` on the metadata
    // row has nothing to push against and the row lands mid-card.
    const link = screen.getByRole("link");
    expect(link.className).toContain("flex-1");
    expect(link.className).toContain("flex-col");
  });

  it("keeps the tile actions reachable without a hover", () => {
    render(
      <MemoryRouter>
        <RecipeCard {...baseProps} recipe={makeRecipe({})} />
      </MemoryRouter>,
    );
    const bar = screen.getByTestId("recipe-delete-btn").parentElement!;
    // `hidden group-hover:flex` means the actions do not exist on a touch
    // screen and never appear for a keyboard user.
    expect(bar.className).not.toContain("hidden");
    expect(bar.className).toContain("group-focus-within:opacity-100");
  });

  it("uses the compact icon size for the delete action instead of a class override", () => {
    render(
      <MemoryRouter>
        <RecipeCard {...baseProps} recipe={makeRecipe({})} />
      </MemoryRouter>,
    );
    const deleteBtn = screen.getByTestId("recipe-delete-btn");
    // `size="iconSm"` is the compact control for action bars; the old bug
    // overrode `size="icon"` with `h-auto`, which twMerge cannot shrink below
    // `md:h-10 md:w-10` on desktop.
    expect(deleteBtn).toHaveClass("h-8", "w-8");
    expect(deleteBtn).not.toHaveClass("h-auto");
    expect(deleteBtn).not.toHaveClass("md:h-10");
    expect(deleteBtn).not.toHaveClass("md:w-10");
  });
});

describe("RecipeCard ingredient coverage", () => {
  it("says what the ratio means, without a title nobody can open", () => {
    render(
      <MemoryRouter>
        <RecipeCard
          {...baseProps}
          recipe={makeRecipe({
            ingredients_total: 5,
            ingredients_available: 4,
            ingredients_incomparable: 0,
          })}
        />
      </MemoryRouter>,
    );

    expect(screen.getByText("4/5 in stock")).toBeInTheDocument();
    expect(screen.getByText("4 of 5 in stock")).toBeInTheDocument();
    // "5/5" alone landed in a row with "2 servings" and "30 min", where a
    // rating is the most natural reading, and the explanation lived in a
    // `title` a touch screen never shows.
    expect(document.querySelector("[title]")).toBeNull();
  });

  it("writes no coverage for a recipe with nothing to check", () => {
    render(
      <MemoryRouter>
        <RecipeCard {...baseProps} recipe={makeRecipe({})} />
      </MemoryRouter>,
    );

    expect(screen.queryByText(/in stock/)).toBeNull();
  });
});
