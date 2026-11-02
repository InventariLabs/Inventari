import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import StatsModuleSettingsPage from "./StatsModuleSettingsPage";
import { ModulesProvider } from "@/contexts/ModulesContext";
import { PageHeaderContext } from "@/hooks/useModulePageHeader";
import { server } from "@/test/mocks/server";
import { signInWith } from "@/test/auth";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn(), loading: vi.fn() },
}));

/**
 * The page sits under the module's own static settings path, which carries no
 * `:name` parameter. Were it to read the name from the route, it would ask the
 * server for the settings of nothing and show an empty form.
 */
describe("StatsModuleSettingsPage", () => {
  beforeEach(() => {
    signInWith(["admin:access"]);
  });

  it("loads and saves the stats module's settings from a path without a module name in it", async () => {
    const user = userEvent.setup();
    let saved: unknown = null;
    server.use(
      http.get("/api/v1/modules/stats/settings", () =>
        HttpResponse.json({
          settings: { forecast_months: 3 },
          settings_schema: {
            type: "object",
            properties: {
              forecast_months: {
                type: "integer",
                title: "Forecast months",
                minimum: 1,
                maximum: 12,
              },
            },
          },
        }),
      ),
      http.put("/api/v1/modules/stats/settings", async ({ request }) => {
        saved = await request.json();
        return HttpResponse.json({ status: "ok" });
      }),
    );
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    render(
      <PageHeaderContext.Provider value={{ data: {}, setHeader: () => {} }}>
        <QueryClientProvider client={queryClient}>
          <ModulesProvider>
            <MemoryRouter initialEntries={["/settings/modules/stats"]}>
              <StatsModuleSettingsPage />
            </MemoryRouter>
          </ModulesProvider>
        </QueryClientProvider>
      </PageHeaderContext.Provider>,
    );

    const field = (await screen.findByTestId(
      "field-forecast_months",
    )) as HTMLInputElement;
    expect(field.value).toBe("3");

    await user.clear(field);
    await user.type(field, "6");
    await user.click(screen.getByRole("button", { name: /Save/i }));

    await waitFor(() =>
      expect(saved).toEqual(expect.objectContaining({ forecast_months: 6 })),
    );
  });
});
