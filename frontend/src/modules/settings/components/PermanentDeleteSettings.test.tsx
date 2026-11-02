import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, beforeEach, vi } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import { server } from "@/test/mocks/server";
import PermanentDeleteSettings from "./PermanentDeleteSettings";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn(), loading: vi.fn() },
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

const baseOrg = {
  id: "org-1",
  name: "Test Org",
  currency: "PLN",
  created_at: "2026-01-01T00:00:00Z",
  created_by: null,
  enabled_modules: ["core", "items"],
  active_profile_id: "food_home",
};

function mockOrg(settings: Record<string, unknown>) {
  server.use(
    http.get("*/organizations/my", () =>
      HttpResponse.json({ ...baseOrg, settings }),
    ),
  );
}

function renderSettings() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <PermanentDeleteSettings />
    </QueryClientProvider>,
  );
}

describe("PermanentDeleteSettings", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    authState.user = { role: "admin", is_superuser: false, permissions: [] };
  });

  it("says the organization could not be loaded instead of showing the switch off", async () => {
    server.use(
      http.get(
        "*/organizations/my",
        () => new HttpResponse(null, { status: 500 }),
      ),
    );
    renderSettings();

    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /try again/i }),
    ).toBeInTheDocument();
    expect(
      screen.queryByTestId("permanent-delete-toggle"),
    ).not.toBeInTheDocument();
  });

  it("writes the flag for an administrator", async () => {
    mockOrg({ show_module_data: true });

    let body: Record<string, unknown> | null = null;
    server.use(
      http.put("*/organizations", async ({ request }) => {
        body = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json({ ...baseOrg, settings: {} });
      }),
    );

    renderSettings();
    await userEvent.click(await screen.findByTestId("permanent-delete-toggle"));

    await waitFor(() => expect(body).not.toBeNull());
    expect(body!.settings).toEqual({
      show_module_data: true,
      allow_permanent_delete: false,
    });
  });

  it("asks before arming an irreversible action", async () => {
    // One click used to be the whole ceremony for handing every deleting user
    // a button that no export undoes.
    mockOrg({ allow_permanent_delete: false });

    let requests = 0;
    server.use(
      http.put("*/organizations", () => {
        requests += 1;
        return HttpResponse.json({ ...baseOrg, settings: {} });
      }),
    );

    renderSettings();
    await userEvent.click(await screen.findByTestId("permanent-delete-toggle"));

    expect(
      await screen.findByText("Allow permanent deletion?"),
    ).toBeInTheDocument();
    expect(requests).toBe(0);

    await userEvent.click(
      screen.getByRole("button", { name: "Allow permanent deletion" }),
    );
    await waitFor(() => expect(requests).toBe(1));
  });

  it("saves nothing when the question is declined", async () => {
    mockOrg({ allow_permanent_delete: false });

    let requests = 0;
    server.use(
      http.put("*/organizations", () => {
        requests += 1;
        return HttpResponse.json({ ...baseOrg, settings: {} });
      }),
    );

    renderSettings();
    const toggle = await screen.findByTestId("permanent-delete-toggle");
    await userEvent.click(toggle);
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));

    expect(requests).toBe(0);
    expect(toggle).not.toBeChecked();
  });

  it("says that switching it off saves by itself", async () => {
    // The card above this one saves on a button; a switch that saves on click
    // has to say so, or the screen has two save models and admits to one.
    mockOrg({ allow_permanent_delete: true });
    renderSettings();

    expect(
      await screen.findByText("Saved as soon as you switch it."),
    ).toBeInTheDocument();
  });

  it("shows a member the policy without a switch they cannot save", async () => {
    // The manager's click used to reach `PUT /organizations`, which is
    // admin-only — an irreversible-deletion policy that looked switchable and
    // was not.
    authState.user = { role: "manager", is_superuser: false, permissions: [] };
    mockOrg({});
    renderSettings();

    const toggle = await screen.findByTestId("permanent-delete-toggle");
    expect(toggle).toBeDisabled();
    expect(
      screen.getByText("Only an administrator can change this."),
    ).toBeInTheDocument();
  });

  it("makes the row itself the checkbox's hit area", async () => {
    // Same class as the module-data card: a 20x20 input a thumb misses. The
    // words toggle the switch now; the safe direction (off) saves directly,
    // which keeps this test out of the confirm dialog's way.
    const user = userEvent.setup();

    let saved: Record<string, unknown> = { allow_permanent_delete: true };
    let body: Record<string, unknown> | null = null;
    server.use(
      http.get("*/organizations/my", () =>
        HttpResponse.json({ ...baseOrg, settings: saved }),
      ),
      http.put("*/organizations", async ({ request }) => {
        body = (await request.json()) as Record<string, unknown>;
        saved = { ...saved, ...(body.settings as Record<string, unknown>) };
        return HttpResponse.json({ ...baseOrg, settings: saved });
      }),
    );
    renderSettings();

    const box = await screen.findByTestId("permanent-delete-toggle");
    expect(box).toBeChecked();

    await user.click(screen.getByText("Permanent deletion"));

    await waitFor(() => expect(body).not.toBeNull());
    expect(body!.settings).toMatchObject({ allow_permanent_delete: false });
    await waitFor(() => expect(box).not.toBeChecked());
  });
});
