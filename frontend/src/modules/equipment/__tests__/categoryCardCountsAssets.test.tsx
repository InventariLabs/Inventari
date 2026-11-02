import React from "react";
import { render, screen, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { http, HttpResponse } from "msw";
import { server } from "@/test/mocks/server";
import { signInWith, signOut } from "@/test/auth";
import { ModulesProvider } from "@/contexts/ModulesContext";
import {
  PageHeaderContext,
  type PageHeaderData,
} from "@/hooks/useModulePageHeader";
import EquipmentCategoriesPage from "../pages/EquipmentCategoriesPage";
import { onePage } from "@/test/mocks/page";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn(), warning: vi.fn() },
}));

/**
 * The card counted the custom fields the category declares — a fact about the
 * form. What a reader is deciding here is whether the category can go, and
 * that is answered by how much is filed under it.
 */

const CATEGORY = {
  id: "cat-1",
  name: "Laptops",
  code: "LAPTOPS",
  context_tag: "equipment",
  icon: null,
  sort_order: 0,
  meta_data: null,
  is_active: true,
  field_definitions: [
    { key: "cpu", label: "CPU", type: "text", visible: true },
    { key: "ram", label: "RAM", type: "text", visible: true },
  ],
  items_count: 17,
};

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });

  function HeaderHost({ children }: { children: React.ReactNode }) {
    const [data, setData] = React.useState<PageHeaderData>({});
    return (
      <PageHeaderContext.Provider value={{ data, setHeader: setData }}>
        {children}
      </PageHeaderContext.Provider>
    );
  }

  const wrapper = ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={queryClient}>
      <ModulesProvider>
        <MemoryRouter>
          <HeaderHost>{children}</HeaderHost>
        </MemoryRouter>
      </ModulesProvider>
    </QueryClientProvider>
  );
  return render(<EquipmentCategoriesPage />, { wrapper });
}

let askedForCounts = false;

beforeEach(() => {
  askedForCounts = false;
  signInWith(["equipment:read", "categories:read", "categories:write"]);
  server.use(
    http.get("/api/v1/categories", ({ request }) => {
      askedForCounts =
        new URL(request.url).searchParams.get("with_counts") === "true";
      return HttpResponse.json(onePage([CATEGORY]));
    }),
  );
});

afterEach(() => {
  signOut();
});

/** The row's cells, in column order.
 *
 * The list renders both responsive branches — the desktop table and the phone
 * card — so the category name is on screen twice. These assertions are about
 * the table's columns, so they read them from the table. */
async function cellsOfRow() {
  const table = await screen.findByRole("table");
  const name = await within(table).findByText("Laptops");
  const cells = name.closest("tr")?.querySelectorAll("td") ?? [];
  return [...cells].map((c) => c.textContent?.trim() ?? "");
}

describe("the equipment category row", () => {
  // The list is a table now (§14.1), so the noun lives in the column header
  // and the cell carries the number. Both facts are still on screen; neither
  // repeats its own label once per row.
  it("says how much is filed under the category", async () => {
    renderPage();

    const [, , assets] = await cellsOfRow();
    expect(assets).toBe("17");
    expect(
      screen.getByRole("columnheader", { name: /assets/i }),
    ).toBeInTheDocument();
  });

  it("asks the endpoint for the counts", async () => {
    renderPage();
    await cellsOfRow();

    // Counts are opt-in on the list endpoint, so a row showing a number
    // without asking for one would be showing a default.
    expect(askedForCounts).toBe(true);
  });

  it("still says how many fields it declares", async () => {
    renderPage();

    // Both facts are worth having; only one of them was there.
    const [, , , fields] = await cellsOfRow();
    expect(fields).toBe("2");
    expect(
      screen.getByRole("columnheader", { name: /fields/i }),
    ).toBeInTheDocument();
  });

  it("explains the empty register on its own line", async () => {
    server.use(
      http.get("/api/v1/categories", () => HttpResponse.json(onePage([]))),
    );

    renderPage();

    const empty = await screen.findByTestId("empty-state");
    expect(
      within(empty).getByRole("heading", {
        level: 2,
        name: "No equipment categories yet",
      }),
    ).toBeInTheDocument();
    expect(
      within(empty).getByText(
        "Create the first category to group assets by type.",
      ),
    ).toBeInTheDocument();
  });
});
