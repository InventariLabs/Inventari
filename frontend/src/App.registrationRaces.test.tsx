import { act, render, screen, waitFor } from "@testing-library/react";
import { describe, it, expect, beforeEach, vi } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import { server } from "@/test/mocks/server";
import { useAuthStore } from "@/store/authStore";
import { ModulesProvider } from "@/contexts/ModulesContext";
import { tokenStore } from "@/lib/api/client";
import { queryKeys } from "@/hooks/queries/keys";
import App from "./App";

/**
 * The registration this file holds open, so the module set can change while
 * the chunks are still on their way — the race the fix exists for.
 */
const gate = vi.hoisted(() => ({
  hold: false,
  waiters: [] as Array<() => void>,
  calls: [] as string[][],
}));

vi.mock("@/lib/moduleRegistry/moduleLoaders", async (importOriginal) => {
  const actual =
    await importOriginal<typeof import("@/lib/moduleRegistry/moduleLoaders")>();
  return {
    ...actual,
    registerModules: async (list: string[]) => {
      gate.calls.push(list);
      if (gate.hold) {
        await new Promise<void>((resolve) => gate.waiters.push(resolve));
      }
      return actual.registerModules(list);
    },
  };
});

const release = () => {
  gate.hold = false;
  gate.waiters.splice(0).forEach((resolve) => resolve());
};

const authState = {
  user: {
    id: "1",
    full_name: "Test User",
    email: "test@example.com",
    preferred_language: "en" as const,
    role: "admin",
    is_active: true,
    is_superuser: false,
    is_blocked: false,
    permissions: [],
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
  },
  isAuthenticated: true,
  isLoading: false,
  authUnavailable: false,
  checkAuth: vi.fn(),
};

describe("the module set changing before its chunks land", () => {
  let queryClient: QueryClient;
  let modules: string[];

  beforeEach(() => {
    vi.clearAllMocks();
    gate.hold = false;
    gate.waiters = [];
    gate.calls = [];
    tokenStore.set("test-token");
    useAuthStore.setState(authState);
    queryClient = new QueryClient({
      defaultOptions: {
        queries: { retry: false },
        mutations: { retry: false },
      },
    });
    modules = ["core"];
    server.use(
      http.get("*/api/v1/modules/my", () => HttpResponse.json(modules)),
      http.get("*/api/v1/about", () =>
        HttpResponse.json({ version: "1.0.0", source_code_url: null }),
      ),
    );
  });

  it("opens the module's route once its chunks land, without a reload", async () => {
    render(
      <QueryClientProvider client={queryClient}>
        <ModulesProvider>
          <App initialEntries={["/inventory"]} />
        </ModulesProvider>
      </QueryClientProvider>,
    );

    // inventory is not in the set yet, so the address is answered by the
    // screen that says so — not by a route that has not been built.
    await screen.findByText("Module Not Enabled");

    // The set gains inventory, and the chunks it needs are held mid-flight:
    // this is the window the routes used to be rebuilt in, too early, with
    // nothing left to rebuild them when the import finished.
    gate.hold = true;
    modules = ["core", "inventory"];
    await act(async () => {
      await queryClient.invalidateQueries({ queryKey: queryKeys.modules.my });
    });
    await waitFor(() => expect(gate.calls.length).toBeGreaterThan(1));

    await act(async () => {
      release();
    });

    // Without a reload, and with no state left stuck at "already registered".
    await waitFor(() =>
      expect(screen.queryByText("Module Not Enabled")).not.toBeInTheDocument(),
    );
    expect(screen.queryByText("Page Not Found")).not.toBeInTheDocument();
  });
});
