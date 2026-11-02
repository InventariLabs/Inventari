/**
 * The wiring behind the error screen: a route that throws must land on
 * `ErrorPage`, not on the boundary above the router.
 *
 * This is the defect in its user-visible form. `errorElement` is armed only
 * by a *data* router, and this application mounted a declarative
 * `<BrowserRouter>`, so the attribute sat on the route tree doing nothing —
 * and the boundary in `main.tsx` (or the one that used to wrap `AppShell`)
 * caught the throw instead and named the failure with its own words, a
 * refresh button among them. The screen the reader got was the one the
 * application never chose.
 *
 * What pins the behaviour is the way out of the screen: `ErrorPage` offers a
 * link home, the boundaries offer only buttons. The link is therefore the mark of
 * the right screen — the shared heading ("Something went wrong") cannot tell
 * the two apart.
 */
import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import { server } from "@/test/mocks/server";
import { useAuthStore } from "@/store/authStore";
import { ModulesProvider } from "@/contexts/ModulesContext";
import { tokenStore } from "@/lib/api/client";
import { createAppRoutes } from "./App";

/** A route component that fails the way a broken screen fails: at render. */
function BrokenScreen(): React.ReactElement {
  throw new Error("planted: the screen broke");
}

describe("the route tree's error screen", () => {
  // The throw below is planted on purpose, so the console gate — which fails
  // a test on any unexpected `console.error` — is told nothing is wrong here
  // by silencing the one call site this test creates. The gate's baseline is
  // left alone: a baseline refreshed to admit an error the test authors is a
  // gate with no teeth left for the error nobody authored.
  beforeEach(() => {
    vi.spyOn(console, "error").mockImplementation(() => {});
  });
  afterEach(() => {
    vi.restoreAllMocks();
  });

  function renderAt(path: string, flatRoutes: unknown[]) {
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
        role: "user",
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      },
      isAuthenticated: true,
      isLoading: false,
      authUnavailable: false,
    });
    server.use(
      http.get("*/api/v1/modules/my", () =>
        HttpResponse.json(["core", "inventory"]),
      ),
    );
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: { retry: false },
        mutations: { retry: false },
      },
    });
    const router = createMemoryRouter(
      createAppRoutes(
        [],
        flatRoutes as Parameters<typeof createAppRoutes>[1],
        [],
      ),
      { initialEntries: [path] },
    );
    render(
      <QueryClientProvider client={queryClient}>
        <ModulesProvider>
          <RouterProvider router={router} />
        </ModulesProvider>
      </QueryClientProvider>,
    );
  }

  it("shows the error screen a route failure was promised, not the boundary above the router", async () => {
    renderAt("/__boom", [{ path: "__boom", component: BrokenScreen }]);

    // The link home is ErrorPage's mark. The boundaries name the same
    // failure with buttons only — no link. The
    // wording itself is ErrorPage's own test's business; this is about which
    // screen is on the glass.
    expect(await screen.findByRole("link", { name: "Go Home" })).toBeTruthy();
  });
});
