import React from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { describe, it, expect, vi } from "vitest";
import { http, HttpResponse } from "msw";
import AssetListPage from "../pages/AssetListPage";
import { server } from "@/test/mocks/server";
import { ModulesProvider } from "@/contexts/ModulesContext";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

vi.mock("@/hooks/useModulePageHeader", () => ({
  useModulePageHeader: () => ({ setHeader: vi.fn() }),
}));

/**
 * The filter row reads two lists, locations and categories. A list that
 * failed to arrive used to leave a filter with only "All Locations" in it —
 * which reads as an organization that has no locations at all.
 */
function renderList(entry: string) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const wrapper = ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={queryClient}>
      <ModulesProvider>
        <MemoryRouter initialEntries={[entry]}>{children}</MemoryRouter>
      </ModulesProvider>
    </QueryClientProvider>
  );
  return render(<AssetListPage />, { wrapper });
}

const failing = (path: string) =>
  http.get(path, () =>
    HttpResponse.json({ detail: "Internal Server Error" }, { status: 500 }),
  );

describe("AssetListPage — a filter list that did not arrive", () => {
  it("says so on the location filter, and a retry asks again", async () => {
    let asked = 0;
    server.use(
      http.get("/api/v1/locations", () => {
        asked += 1;
        return HttpResponse.json(
          { detail: "Internal Server Error" },
          { status: 500 },
        );
      }),
    );
    renderList("/equipment/assets?location=loc-1");

    await userEvent.click(
      await screen.findByRole("combobox", { name: "Filter by location" }),
    );
    expect(
      await screen.findByRole("button", { name: /try again/i }),
    ).toBeInTheDocument();

    const before = asked;
    await userEvent.click(screen.getByRole("button", { name: /try again/i }));
    await vi.waitFor(() => expect(asked).toBeGreaterThan(before));
  });

  it("says so on the category filter instead of offering only 'All Categories'", async () => {
    server.use(failing("/api/v1/categories"));
    renderList("/equipment/assets?category=cat-1");

    expect(
      await screen.findByRole("button", { name: /try again/i }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("combobox", { name: "Filter by category" }),
    ).not.toBeInTheDocument();
  });
});
