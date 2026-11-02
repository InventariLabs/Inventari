import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import RecipeCookingHistory from "./RecipeCookingHistory";

const mockHistory = vi.fn();
const mockPatch = vi.fn();

vi.mock("../hooks/useRecipes", () => ({
  useRecipeHistory: (...args: unknown[]) => mockHistory(...args),
  usePatchCookingHistory: (...args: unknown[]) => mockPatch(...args),
}));

const modulesMock = vi.hoisted(() => ({ documentsEnabled: true }));

vi.mock("@/contexts/ModulesContext", () => ({
  useModules: () => ({
    isModuleEnabled: (name: string) =>
      name === "warehouse" && modulesMock.documentsEnabled,
  }),
}));

vi.mock("sonner", () => ({ toast: { error: vi.fn() } }));

const session = {
  session_id: "s1",
  cooked_at: "2026-07-31T10:00:00Z",
  servings: 2,
  duration_minutes: 15,
  notes: "great meal\ndocument: 11111111-2222-3333-4444-555555555555",
  rating: null,
  items_picked: 2,
  items_skipped: 0,
  items_total: 2,
};

beforeEach(() => {
  vi.clearAllMocks();
  modulesMock.documentsEnabled = true;
  mockHistory.mockReturnValue({
    data: [session],
    isLoading: false,
  });
  mockPatch.mockReturnValue({
    mutateAsync: vi.fn().mockResolvedValue(undefined),
    isPending: false,
  });
});

describe("RecipeCookingHistory — document link", () => {
  it("exposes aria-expanded on the toggle", () => {
    render(
      <MemoryRouter>
        <RecipeCookingHistory recipeId="r1" />
      </MemoryRouter>,
    );
    const toggle = screen.getByRole("button", { name: /cooking history/i });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
  });

  it("renders a link to the audit document and hides the raw id", () => {
    render(
      <MemoryRouter>
        <RecipeCookingHistory recipeId="r1" />
      </MemoryRouter>,
    );
    fireEvent.click(screen.getByText("Cooking history"));
    const link = screen.getByRole("link", { name: /view document/i });
    expect(link).toHaveAttribute(
      "href",
      "/warehouse/documents/11111111-2222-3333-4444-555555555555",
    );
    // Raw marker is not shown as user-facing notes
    expect(screen.queryByText(/document:/i)).not.toBeInTheDocument();
    expect(screen.getByText("great meal")).toBeInTheDocument();
  });

  it("shows no link when the session has no document", () => {
    mockHistory.mockReturnValue({
      data: [{ ...session, notes: "just notes" }],
      isLoading: false,
    });
    render(
      <MemoryRouter>
        <RecipeCookingHistory recipeId="r1" />
      </MemoryRouter>,
    );
    fireEvent.click(screen.getByText("Cooking history"));
    expect(
      screen.queryByRole("link", { name: /view document/i }),
    ).not.toBeInTheDocument();
  });

  it("offers no link where the warehouse module is off, and still hides the raw id", () => {
    modulesMock.documentsEnabled = false;
    render(
      <MemoryRouter>
        <RecipeCookingHistory recipeId="r1" />
      </MemoryRouter>,
    );
    fireEvent.click(screen.getByText("Cooking history"));
    expect(
      screen.queryByRole("link", { name: /view document/i }),
    ).not.toBeInTheDocument();
    expect(screen.queryByText(/document:/i)).not.toBeInTheDocument();
    expect(screen.getByText("great meal")).toBeInTheDocument();
  });
});
