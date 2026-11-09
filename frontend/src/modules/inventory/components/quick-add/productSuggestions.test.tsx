import { describe, it, expect, beforeEach, afterEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { BrowserRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import type { ReactElement } from "react";
import { server } from "@/test/mocks/server";
import { signInWith, signOut } from "@/test/auth";
import { ModulesProvider } from "@/contexts/ModulesContext";
import { PageHeaderContext } from "@/hooks/useModulePageHeader";
import AddItemPage from "../../pages/AddItemPage";
import QuickAddModal from "../QuickAddModal";

/**
 * The save attaches to an existing product only on its exact name, so both
 * doors to the new-product form offer the products already in the catalogue
 * under the name field. A door that stops asking is back to quietly making a
 * second "Soy wax" beside the first, with no unit test to say so.
 */
describe("existing products offered under the name of a new product", () => {
  beforeEach(() => {
    signInWith(["items:read", "items:write"]);
    server.use(
      http.get("/api/v1/items/product-templates", ({ request }) => {
        const search = new URL(request.url).searchParams.get("search") ?? "";
        return HttpResponse.json(
          "soy wax".includes(search.toLowerCase()) && search !== "soy wax"
            ? [{ id: "tpl-1", name: "Soy wax" }]
            : [],
        );
      }),
    );
  });

  afterEach(() => signOut());

  const open = (ui: ReactElement) =>
    render(
      <PageHeaderContext.Provider value={{ data: {}, setHeader: () => {} }}>
        <QueryClientProvider
          client={
            new QueryClient({ defaultOptions: { queries: { retry: false } } })
          }
        >
          <BrowserRouter>
            <ModulesProvider>{ui}</ModulesProvider>
          </BrowserRouter>
        </QueryClientProvider>
      </PageHeaderContext.Provider>,
    );

  /** Types a fragment and clicks the suggestion it brings. */
  async function typeAndPick() {
    const user = userEvent.setup();
    const name = await screen.findByLabelText(/product name/i);
    await user.type(name, "wax");

    const suggestion = await screen.findByRole(
      "button",
      { name: "Soy wax" },
      { timeout: 3000 },
    );
    // Heard when it appears, not only seen: the region is the row itself.
    const heard = suggestion.closest("[role='status']") !== null;
    await user.click(suggestion);
    return { name, heard };
  }

  it("on the add page: picks the exact name and keeps focus in the field", async () => {
    open(<AddItemPage />);

    const { name, heard } = await typeAndPick();

    expect(heard).toBe(true);
    expect(name).toHaveValue("Soy wax");
    // The button is gone after the pick; focus must not fall to the page.
    expect(name).toHaveFocus();
  });

  it("in quick add: picks the exact name and keeps focus in the field", async () => {
    open(<QuickAddModal onClose={() => {}} onSuccess={() => {}} />);

    const { name, heard } = await typeAndPick();

    expect(heard).toBe(true);
    expect(name).toHaveValue("Soy wax");
    expect(name).toHaveFocus();
  });
});
