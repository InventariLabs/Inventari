import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import { describe, it, expect, beforeEach, vi } from "vitest";
import * as modulesCtx from "@/contexts/ModulesContext";
import { server } from "@/test/mocks/server";
import BackgroundShoppingPanel from "./BackgroundShoppingPanel";

function renderPanel() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <BackgroundShoppingPanel />
    </QueryClientProvider>,
  );
}

const summary = (id: string, name: string) => ({
  id,
  name,
  status: "active",
  items: [],
});

describe("BackgroundShoppingPanel", () => {
  beforeEach(() => {
    vi.spyOn(modulesCtx, "useModules").mockReturnValue({
      enabledModules: ["shopping_lists"],
      isModuleEnabled: (name: string) => name === "shopping_lists",
      isLoading: false,
      refreshModules: vi.fn(),
      focusModule: null,
      hiddenModules: [],
    });
  });

  it("names the list it shows when that list is empty", async () => {
    // The panel shows the first of the organization's active lists. With
    // three of them, "List is empty" alone leaves the reader guessing which.
    server.use(
      http.get("/api/v1/shopping-lists", () =>
        HttpResponse.json({
          items: [
            summary("l1", "Weekly groceries"),
            summary("l2", "Party"),
            summary("l3", "Hardware"),
          ],
          total: 3,
          limit: 100,
          offset: 0,
          has_more: false,
        }),
      ),
      http.get("/api/v1/shopping-lists/l1", () =>
        HttpResponse.json(summary("l1", "Weekly groceries")),
      ),
    );
    renderPanel();

    expect(await screen.findByText("List is empty")).toBeInTheDocument();
    expect(screen.getByText("Weekly groceries")).toBeInTheDocument();
  });
});
