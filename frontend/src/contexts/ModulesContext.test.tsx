import { render, screen, waitFor } from "@testing-library/react";
import { describe, it, expect, beforeEach, vi } from "vitest";
import userEvent from "@testing-library/user-event";
import {
  QueryClient,
  QueryClientProvider,
  useQueryClient,
} from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import { server } from "@/test/mocks/server";
import { useAuthStore } from "@/store/authStore";
import { ModulesProvider, useModules } from "./ModulesContext";
import { queryKeys } from "@/hooks/queries/keys";

/**
 * Regression: after a profile switch (or onboarding
 * setup) the frontend must see the new module list without a page reload.
 * The switch flow refreshes the list through the React Query cache
 * (`invalidation.modules`), so ModulesContext must be a consumer of that
 * cache — not a one-shot fetch.
 */
function Probe() {
  const {
    enabledModules,
    isLoading,
    focusModule,
    hiddenModules,
    modulesError,
    focusStatus,
  } = useModules();
  const queryClient = useQueryClient();
  return (
    <div>
      <span data-testid="modules">{enabledModules.join(",")}</span>
      <span data-testid="loading">{String(isLoading)}</span>
      <span data-testid="focus">{focusModule ?? "null"}</span>
      <span data-testid="focus-status">{focusStatus}</span>
      <span data-testid="hidden">{hiddenModules.join(",")}</span>
      <span data-testid="error">{String(modulesError)}</span>
      <button
        onClick={() =>
          queryClient.invalidateQueries({ queryKey: queryKeys.modules.my })
        }
      >
        invalidate
      </button>
    </div>
  );
}

function renderProbe() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <ModulesProvider>
        <Probe />
      </ModulesProvider>
    </QueryClientProvider>,
  );
}

function setUpAuth() {
  useAuthStore.setState({
    user: {
      is_blocked: false,
      permissions: [],
      is_active: true,
      id: "user-1",
      email: "u@example.com",
      full_name: "Test",
      role: "admin",
      is_superuser: false,
      preferred_language: "en",
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    },
    isAuthenticated: true,
  });
}

describe("ModulesContext (refresh after profile switch)", () => {
  beforeEach(() => {
    setUpAuth();
    server.use(
      http.get("*/api/v1/modules/my", () =>
        HttpResponse.json(["core", "items", "locations"]),
      ),
    );
  });

  it("loads the enabled modules on mount", async () => {
    renderProbe();
    await waitFor(() => {
      expect(screen.getByTestId("modules")).toHaveTextContent(
        "core,items,locations",
      );
    });
  });

  it("updates enabledModules after cache invalidation without a reload", async () => {
    renderProbe();
    await waitFor(() => {
      expect(screen.getByTestId("modules")).toHaveTextContent(
        "core,items,locations",
      );
    });

    // Simulate the profile switch: the backend now reports a different set.
    server.use(
      http.get("*/api/v1/modules/my", () =>
        HttpResponse.json(["core", "equipment", "warehouse"]),
      ),
    );
    await userEvent.click(screen.getByRole("button", { name: "invalidate" }));

    await waitFor(() => {
      expect(screen.getByTestId("modules")).toHaveTextContent(
        "core,equipment,warehouse",
      );
    });
  });

  it("falls back to the default list when signed out", async () => {
    useAuthStore.setState({ user: null, isAuthenticated: false });
    renderProbe();
    // Signed out → no fetch; the fallback list (which includes "core")
    // must be visible and the shell must not block on loading.
    await waitFor(() => {
      expect(screen.getByTestId("loading")).toHaveTextContent("false");
    });
    expect(screen.getByTestId("modules")).toHaveTextContent("core,items");
  });
});

describe("ModulesContext — a failed module list is not the default install", () => {
  beforeEach(() => {
    setUpAuth();
  });

  it("reports the outage and offers no modules instead of the default install's list", async () => {
    // A 500 on GET /modules/my used to leave data undefined and substitute
    // FALLBACK_MODULES: the module the organization had switched off came
    // back into the navigation, five enabled modules vanished, and the
    // switched-off module's full route rendered a data panel saying
    // "error / try again" over a 403 that would never go away.
    server.use(
      http.get("*/api/v1/modules/my", () =>
        HttpResponse.json({ detail: "boom" }, { status: 500 }),
      ),
    );
    renderProbe();

    await waitFor(() => {
      expect(screen.getByTestId("error")).toHaveTextContent("true");
    });
    // An empty list offers nothing — core stays reachable, everything else
    // waits for the shell to name the outage. The default install's list
    // must not appear: it names modules this organization does not have.
    expect(screen.getByTestId("modules")).toHaveTextContent("");
    expect(screen.getByTestId("modules")).not.toHaveTextContent("equipment");
  });

  it("clears the outage flag when the list arrives", async () => {
    server.use(
      http.get("*/api/v1/modules/my", () =>
        HttpResponse.json(["core", "items"]),
      ),
    );
    renderProbe();

    await waitFor(() => {
      expect(screen.getByTestId("modules")).toHaveTextContent("core,items");
    });
    expect(screen.getByTestId("error")).toHaveTextContent("false");
  });
});

describe("ModulesContext (focus mode)", () => {
  beforeEach(() => {
    setUpAuth();
  });

  it("hides every other enabled module while focused on one", async () => {
    server.use(
      http.get("*/api/v1/modules/my", () =>
        HttpResponse.json(["core", "equipment", "warehouse"]),
      ),
      http.get("*/api/v1/modules/focus", () =>
        HttpResponse.json({
          applied: true,
          focus_module: "equipment",
          enabled_modules: ["core", "equipment"],
          diff: null,
        }),
      ),
    );
    renderProbe();

    await waitFor(() => {
      expect(screen.getByTestId("focus")).toHaveTextContent("equipment");
    });
    // Every enabled module except the focus module hides from listings.
    const hidden = screen.getByTestId("hidden").textContent;
    expect(hidden?.split(",").sort()).toEqual(["core", "warehouse"]);
  });

  it("hides nothing when the organization is not in focus mode", async () => {
    server.use(
      http.get("*/api/v1/modules/my", () =>
        HttpResponse.json(["core", "equipment"]),
      ),
      http.get("*/api/v1/modules/focus", () =>
        HttpResponse.json({
          applied: false,
          focus_module: null,
          enabled_modules: ["core", "equipment"],
          diff: null,
        }),
      ),
    );
    renderProbe();

    await waitFor(() => {
      expect(screen.getByTestId("focus")).toHaveTextContent("null");
    });
    expect(screen.getByTestId("hidden").textContent).toBe("");
  });

  it("reports a failed focus read instead of passing it off as no focus", async () => {
    // The provider logs the failed read on purpose; this test expects it.
    const errors = vi.spyOn(console, "error").mockImplementation(() => {});
    server.use(
      http.get("*/api/v1/modules/my", () =>
        HttpResponse.json(["core", "equipment"]),
      ),
      http.get("*/api/v1/modules/focus", () =>
        HttpResponse.json({ detail: "boom" }, { status: 500 }),
      ),
    );
    renderProbe();

    await waitFor(() => {
      expect(screen.getByTestId("focus-status")).toHaveTextContent("failed");
    });
    expect(screen.getByTestId("focus")).toHaveTextContent("null");
    expect(errors).toHaveBeenCalled();
    errors.mockRestore();
  });

  it("reports ready once the server has answered", async () => {
    renderProbe();
    await waitFor(() => {
      expect(screen.getByTestId("focus-status")).toHaveTextContent("ready");
    });
  });
});

function Refresher() {
  const { enabledModules, focusModule, refreshModules, refreshFocus } =
    useModules();
  return (
    <div>
      <span data-testid="modules">{enabledModules.join(",")}</span>
      <span data-testid="focus">{focusModule ?? "null"}</span>
      <button onClick={() => void refreshModules()}>refresh modules</button>
      <button onClick={() => void refreshFocus?.()}>refresh focus</button>
    </div>
  );
}

describe("ModulesContext — asking again on demand", () => {
  beforeEach(() => {
    setUpAuth();
  });

  function renderRefresher() {
    const qc = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    return render(
      <QueryClientProvider client={qc}>
        <ModulesProvider>
          <Refresher />
        </ModulesProvider>
      </QueryClientProvider>,
    );
  }

  it("shows the module list the server holds now when a screen asks for a refresh", async () => {
    let enabled = ["core", "items"];
    server.use(
      http.get("*/api/v1/modules/my", () => HttpResponse.json(enabled)),
    );
    renderRefresher();
    await waitFor(() =>
      expect(screen.getByTestId("modules")).toHaveTextContent("core,items"),
    );

    enabled = ["core", "items", "recipes"];
    await userEvent.click(
      screen.getByRole("button", { name: "refresh modules" }),
    );

    await waitFor(() =>
      expect(screen.getByTestId("modules")).toHaveTextContent(
        "core,items,recipes",
      ),
    );
  });

  it("picks up a focus mode switched on elsewhere when a screen asks for a refresh", async () => {
    let focus: string | null = null;
    server.use(
      http.get("*/api/v1/modules/my", () =>
        HttpResponse.json(["core", "equipment"]),
      ),
      http.get("*/api/v1/modules/focus", () =>
        HttpResponse.json({
          applied: focus !== null,
          focus_module: focus,
          enabled_modules: ["core", "equipment"],
          diff: null,
        }),
      ),
    );
    renderRefresher();
    await waitFor(() =>
      expect(screen.getByTestId("focus")).toHaveTextContent("null"),
    );

    focus = "equipment";
    await userEvent.click(
      screen.getByRole("button", { name: "refresh focus" }),
    );

    await waitFor(() =>
      expect(screen.getByTestId("focus")).toHaveTextContent("equipment"),
    );
  });
});
