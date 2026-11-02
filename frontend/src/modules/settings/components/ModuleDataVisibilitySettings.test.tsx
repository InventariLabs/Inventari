import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, beforeEach, vi } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import { server } from "@/test/mocks/server";
import { toast } from "sonner";
import ModuleDataVisibilitySettings from "./ModuleDataVisibilitySettings";

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
      <ModuleDataVisibilitySettings />
    </QueryClientProvider>,
  );
}

describe("ModuleDataVisibilitySettings", () => {
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
    expect(screen.queryByTestId("module-data-toggle")).not.toBeInTheDocument();
  });

  it("starts off — isolation is the default, not a stored choice", async () => {
    mockOrg({});
    renderSettings();

    const toggle = await screen.findByTestId("module-data-toggle");
    await waitFor(() => expect(toggle).not.toBeChecked());
  });

  it("reflects the stored choice when the organization opted in", async () => {
    mockOrg({ show_module_data: true });
    renderSettings();

    const toggle = await screen.findByTestId("module-data-toggle");
    await waitFor(() => expect(toggle).toBeChecked());
  });

  it("writes the flag without dropping the other settings", async () => {
    mockOrg({ allow_permanent_delete: true });

    let body: Record<string, unknown> | null = null;
    server.use(
      http.put("*/organizations", async ({ request }) => {
        body = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json({
          ...baseOrg,
          settings: { allow_permanent_delete: true, show_module_data: true },
        });
      }),
    );

    renderSettings();
    const toggle = await screen.findByTestId("module-data-toggle");
    await userEvent.click(toggle);

    await waitFor(() => expect(body).not.toBeNull());
    expect(body!.settings).toEqual({
      allow_permanent_delete: true,
      show_module_data: true,
    });
  });
  it("says it saves by itself, and says so when it has", async () => {
    mockOrg({});
    server.use(
      http.put("*/organizations", () =>
        HttpResponse.json({
          ...baseOrg,
          settings: { show_module_data: true },
        }),
      ),
    );

    renderSettings();
    expect(
      await screen.findByText("Saved as soon as you switch it."),
    ).toBeInTheDocument();

    await userEvent.click(screen.getByTestId("module-data-toggle"));
    await waitFor(() => expect(toast.success).toHaveBeenCalledWith("Saved"));
  });

  it("describes the switch without naming a module this org may not have", async () => {
    // The description named "Sprzęt" — a module another profile does not
    // install — and mixed four names for two ideas in one sentence.
    mockOrg({});
    renderSettings();

    const description = await screen.findByText(/stays out of the general/);
    expect(description.textContent).not.toMatch(/Inventory|Miejsc|Sprzęt/);
  });

  it("shows a member the policy without a switch they cannot save", async () => {
    // `PUT /organizations` is admin-only. The switch used to be live for a
    // manager, whose click produced a request the API refused.
    authState.user = { role: "manager", is_superuser: false, permissions: [] };
    mockOrg({ show_module_data: true });
    renderSettings();

    const toggle = await screen.findByTestId("module-data-toggle");
    expect(toggle).toBeDisabled();
    expect(
      screen.getByText("Only an administrator can change this."),
    ).toBeInTheDocument();
  });

  it("carries the anchor the hidden-data states deep-link to", async () => {
    // Every "Open settings" on a "kept out of general lists" state targets
    // /settings#module-data — the id is the contract that lands the reader
    // on this card rather than on the top of the page.
    mockOrg({});
    const { container } = renderSettings();

    await screen.findByTestId("module-data-toggle");
    expect(container.querySelector("#module-data")).not.toBeNull();
  });

  it("makes the row itself the checkbox's hit area", async () => {
    // At 390px the input measured 20x20: a target a thumb misses.
    // The row is the label now — the words write the same request the square
    // writes — and the square keeps its size.
    const user = userEvent.setup();

    let saved: Record<string, unknown> = {};
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

    const box = await screen.findByTestId("module-data-toggle");
    expect(box).not.toBeChecked();

    await user.click(screen.getByText("Module data in general lists"));

    await waitFor(() => expect(body).not.toBeNull());
    expect(body!.settings).toMatchObject({ show_module_data: true });
    await waitFor(() => expect(box).toBeChecked());
  });
});
