import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import { server } from "@/test/mocks/server";
import { withLanguage } from "@/test/mocks/i18n";
import { useAuthStore } from "@/store/authStore";
import { WorkspaceModeSettings } from "./WorkspaceModeSettings";
import type {
  ModuleInfo,
  Organization,
  ProductProfile,
  ProfileSwitchResponse,
} from "@/types";
import { onePage } from "@/test/mocks/page";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn(), loading: vi.fn() },
}));

const profiles: ProductProfile[] = [
  {
    id: "food_home",
    name: "Food & Home",
    description: "Track food inventory.",
    default_modules: ["items", "locations"],
    seed_profile: "food_home",
  },
  {
    id: "equipment_wms",
    name: "Equipment & Warehouse",
    description: "Track IT assets.",
    default_modules: ["items", "equipment"],
    seed_profile: "equipment_wms",
  },
  {
    id: "clean_core",
    name: "Custom",
    description: "No industry preset — a neutral base you shape yourself.",
    default_modules: ["items"],
    seed_profile: "clean_core",
  },
];

const org: Organization = {
  can_send_email: false,
  timezone: "UTC",
  currency: "PLN",
  id: "org-1",
  name: "Acme",
  created_at: new Date().toISOString(),
  created_by: null,
  settings: null,
  active_profile_id: "food_home",
  onboarding_completed: true,
};

const moduleCatalog: ModuleInfo[] = [
  {
    module_type: "official",
    capabilities: [],
    optional_requires: [],
    requires_api_key: false,
    is_trusted: false,
    is_always_on: false,
    safety_warnings: [],
    is_configured: true,
    is_premium: false,
    degraded: false,
    frontend_state: "present",
    name: "api_keys",
    display_name: "API Keys",
    description: "Programmatic access.",
    icon: "key",
    category: "integrations",
    requires: [],
    version: "1.0.0",
  },
  {
    module_type: "official",
    capabilities: [],
    optional_requires: [],
    requires_api_key: false,
    is_trusted: false,
    is_always_on: false,
    safety_warnings: [],
    is_configured: true,
    is_premium: false,
    degraded: false,
    frontend_state: "present",
    name: "locations",
    display_name: "Storage Locations",
    description: "Hierarchical storage.",
    icon: "box",
    category: "core",
    requires: [],
    version: "1.0.0",
  },
];

const previewResponse: ProfileSwitchResponse = {
  applied: false,
  diff: {
    disable_all: [],
    from_profile_id: "food_home",
    to_profile_id: "equipment_wms",
    enable: ["equipment"],
    disable: ["locations"],
    cascade_disable: [],
    unchanged: ["items"],
    manual_kept: ["api_keys"],
    final_enabled_modules: ["items", "equipment", "api_keys"],
    module_config_overwrite: ["equipment"],
    warnings: [],
    offer_location_renumbering: false,
  },
};

const applyResponse: ProfileSwitchResponse = {
  ...previewResponse,
  applied: true,
  organization: { ...org, active_profile_id: "equipment_wms" },
};

function renderWorkspace() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <WorkspaceModeSettings />
    </QueryClientProvider>,
  );
}

function setUpAdmin() {
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

function mockBaseEndpoints() {
  server.use(
    http.get("*/api/v1/profiles", () => HttpResponse.json(onePage(profiles))),
    http.get("*/api/v1/organizations/my", () => HttpResponse.json(org)),
    http.get("*/api/v1/modules/available", () =>
      HttpResponse.json(onePage(moduleCatalog)),
    ),
  );
}

async function renderAndSelectEquipment() {
  renderWorkspace();
  await waitFor(() => {
    expect(screen.getByText(/Equipment & Warehouse/)).toBeInTheDocument();
  });
  await userEvent.click(
    screen.getByRole("radio", { name: /Equipment & Warehouse/i }),
  );
}

describe("WorkspaceModeSettings", () => {
  it("shows the current profile and a list of other profiles", async () => {
    setUpAdmin();
    mockBaseEndpoints();
    renderWorkspace();
    await waitFor(() => {
      expect(screen.getByText(/Food & Home/)).toBeInTheDocument();
    });
    expect(screen.getByText(/Equipment & Warehouse/)).toBeInTheDocument();
  });

  it("checks the active profile's radio by default", async () => {
    setUpAdmin();
    mockBaseEndpoints();
    renderWorkspace();
    const current = await screen.findByRole("radio", { name: "Food & Home" });
    expect(current).toBeChecked();
    expect(
      screen.getByRole("radio", { name: "Equipment & Warehouse" }),
    ).not.toBeChecked();
  });

  it("auto-fires preview when a profile radio is selected", async () => {
    setUpAdmin();
    let captured: Record<string, unknown> | null = null;
    mockBaseEndpoints();
    server.use(
      http.post("*/api/v1/onboarding/switch-profile", async ({ request }) => {
        captured = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json(previewResponse);
      }),
    );
    await renderAndSelectEquipment();
    await waitFor(() => {
      expect(captured).toEqual({
        profile_id: "equipment_wms",
        dry_run: true,
      });
    });
    // The diff renders without any further click.
    expect(await screen.findByTestId("workspace-diff")).toBeInTheDocument();
  });

  it("keeps apply disabled until the diff loads", async () => {
    setUpAdmin();
    let openGate: (() => void) | null = null;
    mockBaseEndpoints();
    server.use(
      http.post("*/api/v1/onboarding/switch-profile", async () => {
        await new Promise<void>((resolve) => {
          openGate = resolve;
        });
        return HttpResponse.json(previewResponse);
      }),
    );
    await renderAndSelectEquipment();
    // The preview request is in flight — apply must stay disabled. Pinned by
    // testid: the active card also carries an "Apply again" button, and a
    // role/name query would match both.
    const applyBtn = screen.getByTestId("workspace-apply-button");
    await waitFor(() => expect(openGate).not.toBeNull());
    expect(applyBtn).toBeDisabled();
    openGate!();
    await waitFor(() => expect(applyBtn).not.toBeDisabled());
  });

  it("apply opens a confirm dialog listing disabled modules; confirm posts dry_run=false", async () => {
    setUpAdmin();
    const calls: Array<Record<string, unknown>> = [];
    mockBaseEndpoints();
    server.use(
      http.post("*/api/v1/onboarding/switch-profile", async ({ request }) => {
        const body = (await request.json()) as Record<string, unknown>;
        calls.push(body);
        return HttpResponse.json(
          body.dry_run ? previewResponse : applyResponse,
        );
      }),
    );
    await renderAndSelectEquipment();
    // By testid — "Apply again" on the active card shares the /apply/i name.
    const applyBtn = await screen.findByTestId("workspace-apply-button");
    await waitFor(() => expect(applyBtn).not.toBeDisabled());
    await userEvent.click(applyBtn);

    // The confirm dialog lists the modules being disabled (display names).
    const dialog = await screen.findByRole("alertdialog");
    expect(dialog).toHaveTextContent("Storage Locations");

    await userEvent.click(
      screen.getByRole("button", { name: /switch profile/i }),
    );
    await waitFor(() => {
      expect(calls).toContainEqual({
        profile_id: "equipment_wms",
        dry_run: true,
      });
      expect(calls).toContainEqual({
        profile_id: "equipment_wms",
        dry_run: false,
      });
    });
  });

  it("keeps the apply dialog open and shows the reason when the switch fails", async () => {
    // A failed switch that closed the dialog looked exactly like a successful
    // one: the profile was not switched and the only trace was an unhandled
    // rejection in the console.
    setUpAdmin();
    mockBaseEndpoints();
    server.use(
      http.post("*/api/v1/onboarding/switch-profile", async ({ request }) => {
        const body = (await request.json()) as Record<string, unknown>;
        if (body.dry_run) return HttpResponse.json(previewResponse);
        return HttpResponse.json(
          { detail: "Another switch is in progress" },
          { status: 409 },
        );
      }),
    );
    await renderAndSelectEquipment();
    const applyBtn = await screen.findByTestId("workspace-apply-button");
    await waitFor(() => expect(applyBtn).not.toBeDisabled());
    await userEvent.click(applyBtn);

    await userEvent.click(
      await screen.findByRole("button", { name: /switch profile/i }),
    );

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Another switch is in progress",
    );
    expect(screen.getByRole("alertdialog")).toBeInTheDocument();
  });

  it("offers re-applying the active profile and says what it does", async () => {
    setUpAdmin();
    const calls: Array<Record<string, unknown>> = [];
    mockBaseEndpoints();
    const sameProfilePreview: ProfileSwitchResponse = {
      applied: false,
      diff: {
        disable_all: [],
        from_profile_id: "food_home",
        to_profile_id: "food_home",
        enable: [],
        disable: [],
        cascade_disable: [],
        unchanged: ["items", "locations"],
        manual_kept: [],
        final_enabled_modules: ["items", "locations"],
        module_config_overwrite: [],
        warnings: [],
        offer_location_renumbering: false,
      },
    };
    server.use(
      http.post("*/api/v1/onboarding/switch-profile", async ({ request }) => {
        const body = (await request.json()) as Record<string, unknown>;
        calls.push(body);
        return HttpResponse.json(
          body.dry_run
            ? sameProfilePreview
            : {
                ...sameProfilePreview,
                applied: true,
                organization: org,
              },
        );
      }),
    );
    renderWorkspace();
    // The active profile's card carries the one-click re-apply — a checked
    // radio cannot be re-picked, so the path is a button on the card.
    const reapplyBtn = await screen.findByTestId("workspace-reapply-button");
    expect(reapplyBtn).toHaveTextContent(/apply again/i);

    await userEvent.click(reapplyBtn);
    const dialog = await screen.findByRole("alertdialog");
    // The dialog states what a re-apply does before it can be confirmed.
    expect(dialog).toHaveTextContent(/No modules are added or removed/i);

    await userEvent.click(
      screen.getByRole("button", { name: /run setup again/i }),
    );
    await waitFor(() => {
      expect(calls).toContainEqual({
        profile_id: "food_home",
        dry_run: false,
      });
    });
  });

  it("keeps the re-apply dialog open and shows the reason when the setup fails", async () => {
    setUpAdmin();
    mockBaseEndpoints();
    server.use(
      http.post("*/api/v1/onboarding/switch-profile", () =>
        HttpResponse.json(
          { detail: "The profile setup is locked" },
          { status: 409 },
        ),
      ),
    );
    renderWorkspace();
    const reapplyBtn = await screen.findByTestId("workspace-reapply-button");
    await userEvent.click(reapplyBtn);

    await userEvent.click(
      await screen.findByRole("button", { name: /run setup again/i }),
    );

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "The profile setup is locked",
    );
    expect(screen.getByRole("alertdialog")).toBeInTheDocument();
  });

  it("renders the manual_kept row with module display names", async () => {
    setUpAdmin();
    mockBaseEndpoints();
    server.use(
      http.post("*/api/v1/onboarding/switch-profile", () =>
        HttpResponse.json(previewResponse),
      ),
    );
    await renderAndSelectEquipment();
    const diffPanel = await screen.findByTestId("workspace-diff");
    expect(diffPanel).toHaveTextContent("Kept (added manually)");
    expect(diffPanel).toHaveTextContent("API Keys");
  });

  it("offers renumbering a household's locations and leaves it to the reader", async () => {
    setUpAdmin();
    mockBaseEndpoints();
    server.use(
      http.post("*/api/v1/onboarding/switch-profile", () =>
        HttpResponse.json({
          ...previewResponse,
          diff: { ...previewResponse.diff, offer_location_renumbering: true },
        }),
      ),
    );
    await renderAndSelectEquipment();
    const offer = await screen.findByTestId("workspace-renumber-offer");
    expect(offer).toHaveTextContent("keep scanning");
    expect(offer).toHaveTextContent("Renumber by template");
  });

  it("says nothing about codes when the switch keeps them as they are", async () => {
    setUpAdmin();
    mockBaseEndpoints();
    server.use(
      http.post("*/api/v1/onboarding/switch-profile", () =>
        HttpResponse.json(previewResponse),
      ),
    );
    await renderAndSelectEquipment();
    await screen.findByTestId("workspace-diff");
    expect(
      screen.queryByTestId("workspace-renumber-offer"),
    ).not.toBeInTheDocument();
  });

  it("renders profile names in the user's language, not the registry's English", async () => {
    setUpAdmin();
    mockBaseEndpoints();
    await withLanguage("pl", async () => {
      const { unmount } = renderWorkspace();
      expect(await screen.findByText("Dom i jedzenie")).toBeInTheDocument();
      expect(screen.getByText("Sprzęt i magazyn")).toBeInTheDocument();
      expect(screen.getByText("Własny")).toBeInTheDocument();

      // The English the API sent must not reach the screen — neither as a
      // card label nor as the radio's accessible name, which is what a
      // screen reader announces.
      for (const english of [
        "Food & Home",
        "Equipment & Warehouse",
        "Custom",
      ]) {
        expect(screen.queryByText(english)).not.toBeInTheDocument();
      }
      expect(
        screen.getByRole("radio", { name: "Dom i jedzenie" }),
      ).toBeChecked();
      unmount();
    });
  });

  it("names the target profile in the user's language on the confirm dialog", async () => {
    setUpAdmin();
    mockBaseEndpoints();
    server.use(
      http.post("*/api/v1/onboarding/switch-profile", () =>
        HttpResponse.json(previewResponse),
      ),
    );
    await withLanguage("pl", async () => {
      const { unmount } = renderWorkspace();
      await userEvent.click(
        await screen.findByRole("radio", { name: "Sprzęt i magazyn" }),
      );
      const applyBtn = await screen.findByTestId("workspace-apply-button");
      await waitFor(() => expect(applyBtn).not.toBeDisabled());

      // "Cel: …" next to the apply button — the card label carries the same
      // name, so match the whole interpolated string, not a substring.
      expect(screen.getByText("Cel: Sprzęt i magazyn")).toBeInTheDocument();

      await userEvent.click(applyBtn);
      const dialog = await screen.findByRole("alertdialog");
      expect(dialog).toHaveTextContent("Sprzęt i magazyn");
      expect(dialog).not.toHaveTextContent("Equipment & Warehouse");
      unmount();
    });
  });
});
