import { Suspense } from "react";
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import { moduleRegistry } from "@/lib/moduleRegistry";
import { PageHeaderContext } from "@/hooks/useModulePageHeader";
import { server } from "@/test/mocks/server";
import { signInWith } from "@/test/auth";
import "../module";

/**
 * A module author copies this manifest. Its route is loaded lazily, so a
 * wrong path in the import shows up only when somebody opens /widgets.
 */
describe("example_widgets route, loaded the way the shell loads it", () => {
  it("opens /widgets as the widget list the API returns", async () => {
    signInWith(["example_widgets:read"]);
    server.use(
      http.get("/api/v1/example-widgets", () =>
        HttpResponse.json({
          items: [{ id: "w-1", name: "Gadget", color: "red", quantity: 3 }],
          total: 1,
          limit: 100,
          offset: 0,
          has_more: false,
        }),
      ),
    );
    const [route] = moduleRegistry.getRoutes(["example_widgets"]);
    expect(route.path).toBe("/widgets");
    const Page = route.component;

    render(
      <PageHeaderContext.Provider value={{ data: {}, setHeader: () => {} }}>
        <QueryClientProvider
          client={
            new QueryClient({ defaultOptions: { queries: { retry: false } } })
          }
        >
          <MemoryRouter initialEntries={["/widgets"]}>
            <Suspense fallback={<p>loading</p>}>
              <Page />
            </Suspense>
          </MemoryRouter>
        </QueryClientProvider>
      </PageHeaderContext.Provider>,
    );

    expect(await screen.findByText("Gadget")).toBeInTheDocument();
  });
});
