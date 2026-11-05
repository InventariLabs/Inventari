import { describe, it, expect, beforeEach, afterEach } from "vitest";
import { render, screen } from "@testing-library/react";
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
 * The two doors to the new-product form hand the hook's answer down through
 * the same tab; a door that drops it is back to base fields without a word.
 */
describe("the new-product form with a category list that failed", () => {
  beforeEach(() => {
    signInWith(["items:read", "items:write"]);
    server.use(
      http.get("/api/v1/categories", () =>
        HttpResponse.json({ detail: "boom" }, { status: 500 }),
      ),
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

  it("says so on the add page", async () => {
    open(<AddItemPage />);

    expect(
      await screen.findByText(/categories could not be loaded/i),
    ).toBeInTheDocument();
  });

  it("says so in quick add", async () => {
    open(<QuickAddModal onClose={() => {}} onSuccess={() => {}} />);

    expect(
      await screen.findByText(/categories could not be loaded/i),
    ).toBeInTheDocument();
  });
});
