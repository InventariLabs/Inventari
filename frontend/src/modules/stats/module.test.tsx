import { Suspense } from "react";
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import { moduleRegistry } from "@/lib/moduleRegistry";
import { ModulesProvider } from "@/contexts/ModulesContext";
import { PageHeaderContext } from "@/hooks/useModulePageHeader";
import { server } from "@/test/mocks/server";
import { signInWith } from "@/test/auth";
import "./module";

/**
 * The module's only contribution is its settings entry in the sidebar. It is
 * loaded on demand, so the entry has to be opened through the registry to
 * prove that what the sidebar links to is the stats settings screen.
 */
describe("the stats module's settings entry, loaded the way the sidebar loads it", () => {
  it("opens the stats settings form for the path the sidebar links to", async () => {
    signInWith(["admin:access"]);
    server.use(
      http.get("/api/v1/modules/stats/settings", () =>
        HttpResponse.json({
          settings: { forecast_months: 3 },
          settings_schema: {
            type: "object",
            properties: {
              forecast_months: { type: "integer", title: "Forecast months" },
            },
          },
        }),
      ),
    );
    const [section] = moduleRegistry.getSettingsSections(["stats"]);
    expect(section.path).toBe("modules/stats");
    const Section = section.component;

    render(
      <PageHeaderContext.Provider value={{ data: {}, setHeader: () => {} }}>
        <QueryClientProvider
          client={
            new QueryClient({ defaultOptions: { queries: { retry: false } } })
          }
        >
          <ModulesProvider>
            <MemoryRouter initialEntries={["/settings/modules/stats"]}>
              <Suspense fallback={<p>loading</p>}>
                <Section />
              </Suspense>
            </MemoryRouter>
          </ModulesProvider>
        </QueryClientProvider>
      </PageHeaderContext.Provider>,
    );

    expect(await screen.findByTestId("field-forecast_months")).toHaveValue(3);
  });
});
