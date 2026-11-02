import { render, screen, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import { server } from "@/test/mocks/server";
import { useAuthStore } from "@/store/authStore";
import { ModulesProvider } from "@/contexts/ModulesContext";
import { RootRedirect, LauncherRoute } from "./RootRedirect";
import type { ProductProfile } from "@/types";
import type { ReactNode } from "react";
import { onePage } from "@/test/mocks/page";

vi.mock("@/modules/launcher/components/Launcher", () => ({
  default: () => <div data-testid="launcher">Launcher</div>,
}));

const foodProfile: ProductProfile = {
  id: "food_home",
  name: "Food & Home",
  description: "",
  default_modules: ["items", "locations"],
  seed_profile: "food_home",
};

const equipmentProfile: ProductProfile = {
  id: "equipment_wms",
  name: "Equipment & Warehouse",
  description: "",
  default_modules: ["equipment"],
  seed_profile: "equipment_wms",
};

const cleanProfile: ProductProfile = {
  id: "clean_core",
  name: "Custom",
  description: "",
  default_modules: ["items"],
  seed_profile: "clean_core",
};

const profiles = [foodProfile, equipmentProfile, cleanProfile];

function setOrg(activeProfileId: string | null) {
  server.use(
    http.get("*/api/v1/organizations/my", () =>
      HttpResponse.json({
        id: "org-1",
        name: "Test",
        created_at: new Date().toISOString(),
        created_by: null,
        enabled_modules: ["items", "locations", "equipment"],
        settings: null,
        active_profile_id: activeProfileId,
        onboarding_completed: true,
      }),
    ),
  );
}

function setModules(modules: string[]) {
  server.use(http.get("*/api/v1/modules/my", () => HttpResponse.json(modules)));
}

function renderRoot() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={qc}>
      <ModulesProvider>
        <MemoryRouter initialEntries={["/"]}>
          <Routes>
            <Route path="/" element={children} />
            {/* Mirrors the real alias routes in App.tsx */}
            <Route path="/items" element={<div>ITEMS PAGE</div>} />
            <Route path="/equipment" element={<div>EQUIPMENT PAGE</div>} />
            <Route path="*" element={<div>FALLBACK PAGE</div>} />
          </Routes>
        </MemoryRouter>
      </ModulesProvider>
    </QueryClientProvider>
  );
  return render(<RootRedirect />, { wrapper });
}

beforeEach(() => {
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
  server.use(
    http.get("*/api/v1/profiles", () => HttpResponse.json(onePage(profiles))),
  );
  setOrg("food_home");
  setModules(["core", "items", "locations"]);
});

describe("RootRedirect", () => {
  it("waits for the focus answer instead of starting on the launcher", async () => {
    server.use(
      http.get("*/api/v1/modules/focus", async () => {
        await new Promise((r) => setTimeout(r, 150));
        return HttpResponse.json({
          applied: true,
          focus_module: "equipment",
          enabled_modules: ["core", "items", "equipment"],
          diff: null,
        });
      }),
    );
    setModules(["core", "items", "locations", "equipment"]);
    renderRoot();
    expect(screen.queryByTestId("launcher")).not.toBeInTheDocument();
    expect(await screen.findByText("EQUIPMENT PAGE")).toBeInTheDocument();
    expect(screen.queryByTestId("launcher")).not.toBeInTheDocument();
  });

  it("opens into the focused module in work mode, whatever the profile", async () => {
    server.use(
      http.get("*/api/v1/modules/focus", () =>
        HttpResponse.json({
          applied: true,
          focus_module: "equipment",
          enabled_modules: ["core", "equipment"],
          diff: null,
        }),
      ),
    );
    setOrg("clean_core");
    setModules(["core", "items", "locations", "equipment"]);
    renderRoot();
    expect(await screen.findByText("EQUIPMENT PAGE")).toBeInTheDocument();
    expect(screen.queryByTestId("launcher")).not.toBeInTheDocument();
  });

  it.each(["food_home", "equipment_wms", "clean_core"])(
    "shows the launcher for %s outside work mode, its own module enabled",
    async (profileId) => {
      // Served as the profiles API did while a profile still chose the start
      // screen: a payload that carries the retired `home_route` (an older
      // backend mid-deploy) must not send the reader into a module either.
      const legacyHome: Record<string, string> = {
        food_home: "/items",
        equipment_wms: "/equipment",
      };
      server.use(
        http.get("*/api/v1/profiles", () =>
          HttpResponse.json(
            onePage(
              profiles.map((p) => ({
                ...p,
                home_route: legacyHome[p.id] ?? null,
              })),
            ),
          ),
        ),
      );
      setOrg(profileId);
      setModules(["core", "items", "locations", "equipment"]);
      renderRoot();
      expect(await screen.findByTestId("launcher")).toBeInTheDocument();
      expect(screen.queryByText("ITEMS PAGE")).not.toBeInTheDocument();
      expect(screen.queryByText("EQUIPMENT PAGE")).not.toBeInTheDocument();
    },
  );

  it("falls back to the launcher when no profile is active", async () => {
    setOrg(null);
    renderRoot();
    await waitFor(() => {
      expect(screen.getByTestId("launcher")).toBeInTheDocument();
    });
  });

  it("keeps the Launcher reachable at /launcher", async () => {
    const qc = new QueryClient({
      defaultOptions: {
        queries: { retry: false },
        mutations: { retry: false },
      },
    });
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={qc}>
        <ModulesProvider>
          <MemoryRouter initialEntries={["/launcher"]}>
            <Routes>
              <Route path="/launcher" element={children} />
              <Route path="*" element={<div>FALLBACK PAGE</div>} />
            </Routes>
          </MemoryRouter>
        </ModulesProvider>
      </QueryClientProvider>
    );
    render(<LauncherRoute />, { wrapper });
    expect(await screen.findByTestId("launcher")).toBeInTheDocument();
    expect(screen.queryByText("FALLBACK PAGE")).not.toBeInTheDocument();
  });
});
