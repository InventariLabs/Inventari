import React from "react";
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { http, HttpResponse } from "msw";
import { server } from "@/test/mocks/server";
import { ModuleSettingsScreen } from "./ModuleSettingsScreen";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

vi.mock("@/hooks/useModulePageHeader", () => ({
  useModulePageHeader: () => ({ setHeader: vi.fn() }),
}));

const createWrapper = () => {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>{children}</MemoryRouter>
    </QueryClientProvider>
  );
};

function renderScreen() {
  render(
    <ModuleSettingsScreen moduleName="equipment" title="Equipment settings" />,
    { wrapper: createWrapper() },
  );
}

/**
 * Reading a module's settings is an administrator's right. A manager who
 * followed the nav entry got the same sentence as an outage would produce —
 * no mention of whose permission it is, and nothing to try next.
 */
describe("ModuleSettingsScreen when the settings cannot be shown", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("names the refusal as a permission, not a failure", async () => {
    server.use(
      http.get("/api/v1/modules/equipment/settings", () =>
        HttpResponse.json(
          { detail: "Admin permissions required" },
          { status: 403 },
        ),
      ),
    );

    renderScreen();

    expect(
      await screen.findByText("Only an administrator can open module settings"),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/Ask an administrator of your organization/),
    ).toBeInTheDocument();
    expect(
      screen.queryByText("Failed to load module settings"),
    ).not.toBeInTheDocument();
  });

  it("offers another attempt when the read simply broke", async () => {
    server.use(
      http.get("/api/v1/modules/equipment/settings", () =>
        HttpResponse.json({ detail: "boom" }, { status: 500 }),
      ),
    );

    renderScreen();

    expect(
      await screen.findByText("Failed to load module settings"),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Try again" })).toBeEnabled();
  });

  it("says a module has nothing to configure instead of blaming a failure", async () => {
    server.use(
      http.get("/api/v1/modules/equipment/settings", () =>
        HttpResponse.json({ settings: {}, settings_schema: null }),
      ),
    );

    renderScreen();

    expect(
      await screen.findByText("This module has no settings"),
    ).toBeInTheDocument();
  });
});
