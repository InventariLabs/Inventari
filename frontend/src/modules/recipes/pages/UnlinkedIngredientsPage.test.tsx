import React, { useState } from "react";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter } from "react-router-dom";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { http, HttpResponse } from "msw";
import { toast } from "sonner";
import { signInWith, signOut } from "@/test/auth";
import { server } from "@/test/mocks/server";
import { PageHeaderContext } from "@/hooks/useModulePageHeader";
import UnlinkedIngredientsPage from "./UnlinkedIngredientsPage";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn(), info: vi.fn() },
}));

vi.mock("@/contexts/ModulesContext", () => ({
  useModules: () => ({
    enabledModules: ["recipes"],
    isModuleEnabled: (name: string) => name === "recipes",
    isLoading: false,
    refreshModules: vi.fn(),
  }),
}));

const UNLINKED_URL = "/api/v1/recipes/ingredients/unlinked";
const PROPOSALS_URL = "/api/v1/recipes/ingredients/match-proposals";
const LINK_URL = "/api/v1/recipes/ingredients/link-templates";
const PURPOSES_URL = "/api/v1/ai-connections/purposes";

const unlinkedPayload = {
  items: [
    {
      id: "ing-1",
      recipe_id: "rec-a",
      recipe_name: "Recipe A",
      name: "Onion",
      match_name: "onion",
      quantity: "2",
      uom_symbol: "pcs",
    },
    {
      id: "ing-2",
      recipe_id: "rec-b",
      recipe_name: "Recipe B",
      name: "Carrot",
      match_name: "carrot",
      quantity: "1",
      uom_symbol: null,
    },
  ],
  total: 2,
  limit: 200,
  offset: 0,
  has_more: false,
  ingredient_total: 3,
};

function createWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return ({ children }: { children: React.ReactNode }) => {
    const [headerData, setHeaderData] = useState<{
      title?: string;
      subtitle?: string;
      actions?: React.ReactNode;
    }>({});
    return (
      <PageHeaderContext.Provider
        value={{ data: headerData, setHeader: setHeaderData }}
      >
        <QueryClientProvider client={queryClient}>
          <BrowserRouter>
            {headerData.actions && <div>{headerData.actions}</div>}
            {children}
          </BrowserRouter>
        </QueryClientProvider>
      </PageHeaderContext.Provider>
    );
  };
}

describe("UnlinkedIngredientsPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    signInWith(["recipes:read", "recipes:write"]);
  });

  afterEach(() => {
    signOut();
  });

  it("lists the backlog and writes approved proposals in one call", async () => {
    const linkBodies: unknown[] = [];
    server.use(
      http.get(UNLINKED_URL, () => HttpResponse.json(unlinkedPayload)),
      http.post(PROPOSALS_URL, () =>
        HttpResponse.json({
          proposals: [
            {
              ingredient_id: "ing-1",
              template_id: "tpl-1",
              template_name: "Onion Powder",
            },
          ],
          considered: 2,
        }),
      ),
      http.post(LINK_URL, async ({ request }) => {
        linkBodies.push(await request.json());
        return HttpResponse.json({ linked: 1, recipe_ids: ["rec-a"] });
      }),
    );
    const user = userEvent.setup();
    render(<UnlinkedIngredientsPage />, { wrapper: createWrapper() });

    await screen.findByText("Onion");
    expect(screen.getByText("Carrot")).toBeInTheDocument();
    expect(screen.getByText("Recipe A")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Find matches" }));

    expect(await screen.findByText("Onion Powder")).toBeInTheDocument();
    // The proposal arrives ticked — approving it is the whole gesture.
    const rowCheckbox = screen.getByRole("checkbox", {
      name: "Select the proposal for Onion",
    });
    expect(rowCheckbox).toBeChecked();

    await user.click(screen.getByRole("button", { name: /Link selected/ }));

    await waitFor(() => expect(linkBodies).toHaveLength(1));
    expect(linkBodies[0]).toEqual({
      links: [{ ingredient_id: "ing-1", template_id: "tpl-1" }],
    });
    expect(toast.success).toHaveBeenCalledWith("1 ingredient linked");
  });

  it("answers an unbound-AI refusal with the purpose label and the way to fix it", async () => {
    server.use(
      http.get(UNLINKED_URL, () => HttpResponse.json(unlinkedPayload)),
      http.post(PROPOSALS_URL, () =>
        HttpResponse.json(
          {
            detail: {
              code: "LLM_PURPOSE_UNBOUND",
              message: "No AI connection has been chosen for this feature yet.",
            },
          },
          { status: 503 },
        ),
      ),
    );
    const user = userEvent.setup();
    render(<UnlinkedIngredientsPage />, { wrapper: createWrapper() });

    await screen.findByText("Onion");
    await user.click(screen.getByRole("button", { name: "Find matches" }));

    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith(
        expect.stringContaining("Read a recipe from text"),
      ),
    );
    expect(toast.error).toHaveBeenCalledWith(
      expect.stringContaining("Settings → AI Connections"),
    );
    expect(toast.error).not.toHaveBeenCalledWith("Could not match ingredients");
  });

  /**
   * Deliberate degradation, not regression teeth.
   *
   * Only the label of the unbound-AI refusal reads the purpose registry; the
   * comment in the page says so, and this is the proof of that sentence: the
   * registry read fails, the backlog stays on the screen with its write
   * controls, and the refusal still names the purpose in the words the reader
   * knows instead of the raw registry key. It passes on the source without
   * the query-error work as well — the failure state is a fallback the page
   * chose, not a guard the read added.
   */
  it("stays usable when the purpose registry read fails, and the refusal still names the purpose", async () => {
    server.use(
      http.get(UNLINKED_URL, () => HttpResponse.json(unlinkedPayload)),
      http.get(PURPOSES_URL, () =>
        HttpResponse.json({ detail: "registry down" }, { status: 500 }),
      ),
      http.post(PROPOSALS_URL, () =>
        HttpResponse.json(
          {
            detail: {
              code: "LLM_PURPOSE_UNBOUND",
              message: "No AI connection has been chosen for this feature yet.",
            },
          },
          { status: 503 },
        ),
      ),
    );
    const user = userEvent.setup();
    render(<UnlinkedIngredientsPage />, { wrapper: createWrapper() });

    expect(await screen.findByText("Onion")).toBeInTheDocument();
    expect(screen.getByText("Carrot")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Find matches" }),
    ).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Find matches" }));

    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith(
        expect.stringContaining("Read a recipe from text"),
      ),
    );
    // The registry key itself never reaches the reader.
    expect(toast.error).not.toHaveBeenCalledWith(
      expect.stringContaining("purposeLabel"),
    );
    expect(toast.error).not.toHaveBeenCalledWith("Could not match ingredients");
  });

  it("offers no write controls to a read-only account", async () => {
    signInWith(["recipes:read"]);
    server.use(
      http.get(UNLINKED_URL, () => HttpResponse.json(unlinkedPayload)),
    );
    render(<UnlinkedIngredientsPage />, { wrapper: createWrapper() });

    await screen.findByText("Onion");
    expect(
      screen.queryByRole("button", { name: "Find matches" }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole("checkbox", {
        name: "Select the proposal for Onion",
      }),
    ).toBeDisabled();
  });

  it("offers no matching for a list that failed to load", async () => {
    server.use(
      http.get(UNLINKED_URL, () =>
        HttpResponse.json({ detail: "down" }, { status: 500 }),
      ),
    );
    render(<UnlinkedIngredientsPage />, { wrapper: createWrapper() });

    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "Find matches" }),
      ).toBeDisabled(),
    );
    expect(
      screen.queryByText("Every ingredient is linked"),
    ).not.toBeInTheDocument();
  });

  it("shows the all-linked empty state when the backlog is empty", async () => {
    server.use(
      http.get(UNLINKED_URL, () =>
        HttpResponse.json({
          items: [],
          total: 0,
          limit: 200,
          offset: 0,
          has_more: false,
          ingredient_total: 4,
        }),
      ),
    );
    render(<UnlinkedIngredientsPage />, { wrapper: createWrapper() });

    expect(
      await screen.findByText("Every ingredient is linked"),
    ).toBeInTheDocument();
  });

  it("does not claim everything is linked when no recipe has an ingredient", async () => {
    server.use(
      http.get(UNLINKED_URL, () =>
        HttpResponse.json({
          items: [],
          total: 0,
          limit: 200,
          offset: 0,
          has_more: false,
          ingredient_total: 0,
        }),
      ),
    );
    render(<UnlinkedIngredientsPage />, { wrapper: createWrapper() });

    expect(
      await screen.findByText("No recipe ingredients yet"),
    ).toBeInTheDocument();
    expect(
      screen.queryByText("Every ingredient is linked"),
    ).not.toBeInTheDocument();
  });
});
