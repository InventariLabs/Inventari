import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { signInWith, signOut } from "@/test/auth";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import ModuleSettingsPage from "./ModuleSettingsPage";
import { ModulesProvider } from "@/contexts/ModulesContext";
import { PageHeaderContext } from "@/hooks/useModulePageHeader";
import { server } from "@/test/mocks/server";
import { http, HttpResponse } from "msw";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn(), loading: vi.fn() },
}));

const schema = {
  type: "object" as const,
  properties: {
    threshold: {
      type: "integer" as const,
      title: "Threshold",
      minimum: 1,
      maximum: 100,
      default: 10,
    },
    enabled: { type: "boolean" as const, title: "Enabled" },
    jina: {
      type: "object" as const,
      properties: {
        api_key: {
          type: "string" as const,
          format: "secret" as const,
          title: "Jina API key",
        },
      },
    },
  },
};

const settingsResponse = {
  settings: {
    threshold: 5,
    enabled: true,
    jina: { api_key: "**********" },
  },
  settings_schema: schema,
};

const renderPage = (
  name: string,
  setHeader: (data: unknown) => void = () => {},
) => {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <PageHeaderContext.Provider value={{ data: {}, setHeader }}>
      <QueryClientProvider client={qc}>
        <ModulesProvider>
          <MemoryRouter initialEntries={[`/settings/modules/${name}`]}>
            <Routes>
              <Route
                path="/settings/modules/:name"
                element={<ModuleSettingsPage />}
              />
              <Route
                path="/apps"
                element={<div data-testid="app-store-stub" />}
              />
            </Routes>
          </MemoryRouter>
        </ModulesProvider>
      </QueryClientProvider>
    </PageHeaderContext.Provider>,
  );
};

describe("ModuleSettingsPage — auto-UI for module settings", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    // Saving module settings is `admin:access` on the API — the form now
    // asks for it, and these tests exercise the form.
    signInWith(["admin:access"]);
    server.use(
      http.get("/api/v1/modules/webhooks/settings", () =>
        HttpResponse.json(settingsResponse),
      ),
      http.put("/api/v1/modules/webhooks/settings", () =>
        HttpResponse.json({ status: "ok" }),
      ),
    );
  });

  it("renders fields for each schema property", async () => {
    renderPage("webhooks");
    await waitFor(() => {
      expect(screen.getByTestId("field-threshold")).toBeInTheDocument();
    });
    expect(screen.getByTestId("field-enabled")).toBeInTheDocument();
    expect(screen.getByTestId("field-jina.api_key")).toBeInTheDocument();
  });

  it("populates initial values from server", async () => {
    renderPage("webhooks");
    await waitFor(() => {
      const input = screen.getByTestId("field-threshold") as HTMLInputElement;
      expect(input.value).toBe("5");
    });
  });

  it("sends a PUT with the edited value", async () => {
    const user = userEvent.setup();
    let captured: unknown = null;
    server.use(
      http.put("/api/v1/modules/webhooks/settings", async ({ request }) => {
        captured = await request.json();
        return HttpResponse.json({ status: "ok" });
      }),
    );

    renderPage("webhooks");
    await waitFor(() => {
      expect(screen.getByTestId("field-threshold")).toBeInTheDocument();
    });

    const input = screen.getByTestId("field-threshold") as HTMLInputElement;
    await user.clear(input);
    await user.type(input, "42");

    await user.click(screen.getByRole("button", { name: /Save/i }));

    await waitFor(() => {
      expect(captured).toEqual(expect.objectContaining({ threshold: 42 }));
    });
  });

  it("does NOT send a masked secret that the user did not edit", async () => {
    const user = userEvent.setup();
    let captured: unknown = null;
    server.use(
      http.put("/api/v1/modules/webhooks/settings", async ({ request }) => {
        captured = await request.json();
        return HttpResponse.json({ status: "ok" });
      }),
    );

    renderPage("webhooks");
    await waitFor(() => {
      expect(screen.getByTestId("field-threshold")).toBeInTheDocument();
    });
    // Another field is edited so there is a Save to press; the secret is not.
    const input = screen.getByTestId("field-threshold") as HTMLInputElement;
    await user.clear(input);
    await user.type(input, "7");
    await user.click(screen.getByRole("button", { name: /Save/i }));
    await waitFor(() => {
      expect(captured).toEqual(expect.objectContaining({ threshold: 7 }));
      expect(captured).not.toHaveProperty("jina.api_key");
    });
  });

  it("renders an empty state when schema has no properties", async () => {
    server.use(
      http.get("/api/v1/modules/webhooks/settings", () =>
        HttpResponse.json({
          settings: {},
          settings_schema: { type: "object", properties: {} },
        }),
      ),
    );
    renderPage("webhooks");
    await waitFor(() => {
      expect(screen.getByTestId("empty-state")).toBeInTheDocument();
    });
  });
});

describe("ModuleSettingsPage — an enabled feature is not an unknown module", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  // The products domain has no settings schema, and the settings endpoint
  // answers with one: `items` sits enabled in every organization, so the
  // screen may say "no settings" — never "no such module".
  it("answers a known feature without a schema with no-settings copy", async () => {
    server.use(
      http.get("/api/v1/modules/items/settings", () =>
        HttpResponse.json({ settings: {}, settings_schema: null }),
      ),
    );
    renderPage("items");
    await waitFor(() => {
      expect(
        screen.getByText("This module has no settings"),
      ).toBeInTheDocument();
    });
    expect(
      screen.queryByText("There is no module by that name"),
    ).not.toBeInTheDocument();
  });

  it("names the products feature by its card, not its slug", async () => {
    server.use(
      http.get("/api/v1/modules/items/settings", () =>
        HttpResponse.json({ settings: {}, settings_schema: null }),
      ),
    );
    const setHeader = vi.fn();
    renderPage("items", setHeader);
    await waitFor(() => {
      expect(setHeader).toHaveBeenCalledWith(
        expect.objectContaining({ title: "Inventory" }),
      );
    });
  });

  // A name the installation genuinely does not have keeps the unknown-module
  // answer — the repair above must not swallow it.
  it("keeps the unknown-module copy for a name outside the installation", async () => {
    server.use(
      http.get("/api/v1/modules/no-such-thing/settings", () =>
        HttpResponse.json(
          { detail: { code: "MODULE_NOT_FOUND", message: "Module not found" } },
          { status: 404 },
        ),
      ),
    );
    renderPage("no-such-thing");
    await waitFor(() => {
      expect(
        screen.getByText("There is no module by that name"),
      ).toBeInTheDocument();
    });
  });
});

describe("ModuleSettingsPage — opened without a module", () => {
  it("says where to open one from instead of just naming the gap", () => {
    const qc = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    render(
      <PageHeaderContext.Provider value={{ data: {}, setHeader: () => {} }}>
        <QueryClientProvider client={qc}>
          <ModulesProvider>
            <MemoryRouter>
              <ModuleSettingsPage />
            </MemoryRouter>
          </ModulesProvider>
        </QueryClientProvider>
      </PageHeaderContext.Provider>,
    );

    expect(screen.getByText("Unnamed module")).toBeInTheDocument();
    expect(
      screen.getByText(
        "Open a module from the Apps screen to see its settings.",
      ),
    ).toBeInTheDocument();
  });
});

afterEach(signOut);
