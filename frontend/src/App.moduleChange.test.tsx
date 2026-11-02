import { act, render, screen, waitFor } from "@testing-library/react";
import { describe, it, expect, beforeEach } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import { server } from "@/test/mocks/server";
import { useAuthStore } from "@/store/authStore";
import { ModulesProvider } from "@/contexts/ModulesContext";
import { tokenStore } from "@/lib/api/client";
import { queryKeys } from "@/hooks/queries/keys";
import App from "./App";

// Applying a workspace profile changes the organization's module list while
// the reader is on /settings/my-modules. The route tree is rebuilt for the new
// list, and the reader must stay on the page that just confirmed the switch.
// With a module leaving the list, a legacy redirect used to render in the
// settings page's place and send the reader to the start screen.
describe("a module list that changes under the reader", () => {
  let queryClient: QueryClient;
  let modules: string[];
  let moduleListReads: number;

  beforeEach(() => {
    tokenStore.set("test-token");
    useAuthStore.setState({
      user: {
        is_blocked: false,
        is_superuser: false,
        permissions: [],
        is_active: true,
        id: "1",
        full_name: "Test User",
        email: "test@example.com",
        preferred_language: "en",
        role: "admin",
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      },
      isAuthenticated: true,
    });
    queryClient = new QueryClient({
      defaultOptions: {
        queries: { retry: false },
        mutations: { retry: false },
      },
    });
    modules = ["core", "inventory"];
    moduleListReads = 0;
    server.use(
      http.get("*/api/v1/modules/my", () => {
        moduleListReads += 1;
        return HttpResponse.json(modules);
      }),
      http.get("*/api/v1/about", () =>
        HttpResponse.json({ version: "1.0.0", source_code_url: null }),
      ),
    );
  });

  it("keeps the page it was on when a module leaves the list", async () => {
    modules = ["core", "inventory", "warehouse"];
    render(
      <QueryClientProvider client={queryClient}>
        <ModulesProvider>
          <App initialEntries={["/settings/about"]} />
        </ModulesProvider>
      </QueryClientProvider>,
    );
    const copyright = /Copyright ©/;
    await screen.findByText(copyright);

    modules = ["core", "inventory"];
    await act(async () => {
      await queryClient.invalidateQueries({ queryKey: queryKeys.modules.my });
    });
    await waitFor(() => expect(moduleListReads).toBeGreaterThan(1));
    // Give the rebuilt router the turns it needs to redirect, if it will.
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 300));
    });

    expect(screen.queryByText(copyright)).not.toBeNull();
  });
});

// A nav entry that hides is not a gate: the stock-take screens used to render
// by address while their module was off, in work mode or not.
describe("routes that need a module", () => {
  beforeEach(() => {
    tokenStore.set("test-token");
    useAuthStore.setState({
      user: {
        is_blocked: false,
        is_superuser: true,
        permissions: [],
        is_active: true,
        id: "1",
        full_name: "Test User",
        email: "test@example.com",
        preferred_language: "en",
        role: "admin",
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      },
      isAuthenticated: true,
    });
  });

  it("names the stock-takes module as off when its screens are asked for", async () => {
    // The counting screens are the module's own, hosted in the inventory
    // shell and mounted only while it is on; with it off the address is
    // owned by a module the organization has not switched on.
    server.use(
      http.get("*/api/v1/modules/my", () =>
        HttpResponse.json(["core", "inventory"]),
      ),
    );
    render(
      <QueryClientProvider client={new QueryClient()}>
        <ModulesProvider>
          <App initialEntries={["/inventory/stock-takes"]} />
        </ModulesProvider>
      </QueryClientProvider>,
    );
    expect(await screen.findByText("Module Not Enabled")).toBeInTheDocument();
  });
});
