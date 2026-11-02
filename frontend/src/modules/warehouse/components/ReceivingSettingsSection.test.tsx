import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { http, HttpResponse } from "msw";
import { server } from "@/test/mocks/server";
import { queryKeys } from "@/hooks/queries/keys";
import { ReceivingSettingsSection } from "./ReceivingSettingsSection";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

const authState = {
  user: { role: "admin", is_superuser: false, permissions: [] as string[] },
  isAuthenticated: true,
  isLoading: false,
};

vi.mock("@/store/authStore", () => ({
  useAuthStore: (selector?: (s: typeof authState) => unknown) =>
    selector ? selector(authState) : authState,
}));

const schemaResponse = {
  settings: { over_receipt_tolerance_pct: 0 },
  settings_schema: {
    type: "object",
    properties: {
      over_receipt_tolerance_pct: {
        type: "number",
        title: "Over-receipt tolerance (%)",
        default: 0,
      },
    },
  },
};

const settingsKey = queryKeys.modules.settings("warehouse");

function renderSection(queryClient = newQueryClient()) {
  render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <ReceivingSettingsSection />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return queryClient;
}

function newQueryClient() {
  return new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
}

/**
 * The Settings screen holds the profile for everyone and the module's own
 * options for an administrator. The section must say nothing to anyone else —
 * not a refusal, and not a request that can only come back as one.
 */
describe("ReceivingSettingsSection", () => {
  beforeEach(() => {
    authState.user = {
      role: "admin",
      is_superuser: false,
      permissions: [],
    };
    server.use(
      http.get("/api/v1/modules/warehouse/settings", () =>
        HttpResponse.json(schemaResponse),
      ),
    );
  });

  it("shows the over-receipt tolerance to an administrator", async () => {
    renderSection();

    expect(
      await screen.findByText("Over-receipt tolerance (%)"),
    ).toBeInTheDocument();
  });

  it("renders nothing, and asks for nothing, for anyone else", () => {
    authState.user = {
      role: "manager",
      is_superuser: false,
      permissions: [],
    };
    // With the settings already cached, an ungated section renders on its
    // first render, without waiting for any response. What it would hold for
    // a manager is the form's read-only notice, not the tolerance, so the
    // check is for the section itself.
    const queryClient = newQueryClient();
    queryClient.setQueryData(settingsKey, schemaResponse);

    renderSection(queryClient);

    expect(document.body.querySelector("section")).toBeNull();
    // A query that is never subscribed to can never be sent.
    expect(
      queryClient
        .getQueryCache()
        .find({ queryKey: settingsKey })
        ?.getObserversCount(),
    ).toBe(0);
  });

  it("stays out of the way when the module has no schema", async () => {
    server.use(
      http.get("/api/v1/modules/warehouse/settings", () =>
        HttpResponse.json({ settings: {}, settings_schema: null }),
      ),
    );

    const queryClient = renderSection();

    await waitFor(() =>
      expect(queryClient.getQueryState(settingsKey)?.status).toBe("success"),
    );
    expect(document.body.querySelector("section")).toBeNull();
  });
});
