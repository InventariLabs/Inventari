import { describe, it, expect, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { RecipesPageHeaderActions } from "./RecipesPageHeaderActions";
import en from "@/modules/recipes/i18n/en.json";
import common from "@/i18n/locales/en/common.json";
import type { TFunction } from "i18next";

const t = ((key: string) => {
  const ns = key.startsWith("common:") ? common : en;
  const path = key.replace(/^(common|recipes):/, "").split(".");
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  let value: any = ns;
  for (const part of path) value = value?.[part];
  return typeof value === "string" ? value : key;
}) as unknown as TFunction;

const baseProps = {
  selectionMode: false,
  hasRecipes: true,
  hasTags: true,
  t,
  onToggleSelectionMode: vi.fn(),
  onToggleTags: vi.fn(),
  onToggleImport: vi.fn(),
  onNewCollection: vi.fn(),
  onNewRecipe: vi.fn(),
};

describe("RecipesPageHeaderActions — a11y labels", () => {
  it("labels every icon-only button", () => {
    render(<RecipesPageHeaderActions {...baseProps} />);
    expect(screen.getByRole("button", { name: "Tags" })).toHaveAttribute(
      "aria-label",
      "Tags",
    );
    expect(
      screen.getByRole("button", { name: "Import recipe" }),
    ).toHaveAttribute("aria-label", "Import recipe");
    expect(
      screen.getByRole("button", { name: "Select recipes" }),
    ).toHaveAttribute("aria-label", "Select recipes");
  });

  /**
   * The gear duplicated the module's own Settings tab — and led somewhere
   * else while doing it: the tab opens the module's settings, the gear
   * opened the App Store copy the module settings page was created to
   * replace.
   */
  it("leaves settings to the module's own navigation entry", () => {
    render(<RecipesPageHeaderActions {...baseProps} />);
    expect(screen.queryByRole("button", { name: "Settings" })).toBeNull();
  });
});

describe("RecipesPageHeaderActions — tools over an empty list", () => {
  it("drops batch selection and the tag manager when there is neither", () => {
    render(
      <RecipesPageHeaderActions
        {...baseProps}
        hasRecipes={false}
        hasTags={false}
      />,
    );

    expect(
      screen.queryByRole("button", { name: "Select recipes" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Tags" }),
    ).not.toBeInTheDocument();
    // Import and "new recipe" are how the list stops being empty.
    expect(
      screen.getByRole("button", { name: "Import recipe" }),
    ).toBeInTheDocument();
  });

  it("keeps the way out of selection mode when the last recipe goes", () => {
    render(
      <RecipesPageHeaderActions
        {...baseProps}
        hasRecipes={false}
        selectionMode
      />,
    );

    expect(
      screen.getByRole("button", { name: "Select recipes" }),
    ).toBeInTheDocument();
  });
});

describe("RecipesPageHeaderActions — collections", () => {
  it("offers a new collection in the bar with the page's other verbs", () => {
    // It used to live only in the sidebar, and on a phone in a dashed chip
    // over the list — never where the reader looks for what a page can do.
    render(<RecipesPageHeaderActions {...baseProps} />);

    expect(
      screen.getByRole("button", { name: "New collection" }),
    ).toBeInTheDocument();
  });

  it("does not offer a folder for nothing", () => {
    render(<RecipesPageHeaderActions {...baseProps} hasRecipes={false} />);

    expect(
      screen.queryByRole("button", { name: "New collection" }),
    ).not.toBeInTheDocument();
  });
});

describe("RecipesPageHeaderActions — on a phone", () => {
  /**
   * Four icons beside one named action left the reader guessing which one
   * imports and which starts selecting. Below `sm` they collapse into a menu
   * whose rows carry the names.
   */
  it("spells out every tool in one menu", async () => {
    const user = userEvent.setup();
    const onToggleImport = vi.fn();
    render(
      <RecipesPageHeaderActions
        {...baseProps}
        onToggleImport={onToggleImport}
      />,
    );

    await user.click(screen.getByRole("button", { name: "More actions" }));
    const menu = document.querySelector("[data-radix-popper-content-wrapper]");
    expect(menu).not.toBeNull();
    const inMenu = within(menu as HTMLElement);
    for (const name of [
      "Tags",
      "Import recipe",
      "New collection",
      "Select recipes",
    ]) {
      expect(inMenu.getByRole("button", { name })).toHaveTextContent(name);
    }

    await user.click(inMenu.getByRole("button", { name: "Import recipe" }));
    expect(onToggleImport).toHaveBeenCalledTimes(1);
  });

  it("offers the menu only the tools that apply", async () => {
    const user = userEvent.setup();
    render(
      <RecipesPageHeaderActions
        {...baseProps}
        hasRecipes={false}
        hasTags={false}
      />,
    );

    await user.click(screen.getByRole("button", { name: "More actions" }));
    const menu = document.querySelector(
      "[data-radix-popper-content-wrapper]",
    ) as HTMLElement;
    expect(within(menu).getAllByRole("button")).toHaveLength(1);
  });
});
