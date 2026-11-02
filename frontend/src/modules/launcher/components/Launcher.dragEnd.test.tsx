import { render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { http, HttpResponse } from "msw";
import { Home } from "lucide-react";
import type { ComponentProps } from "react";
import { act } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { DragEndEvent } from "@dnd-kit/core";
import { server } from "@/test/mocks/server";
import { moduleRegistry, type FrontendModule } from "@/lib/moduleRegistry";
import { useAuthStore } from "@/store/authStore";
import { ModulesProvider } from "@/contexts/ModulesContext";
import { onePage } from "@/test/mocks/page";
import type { LauncherCategory, Organization } from "@/types";
import Launcher from "./Launcher";
import { forgetFirstVisits } from "../hooks/useLauncherGreeting";

/**
 * A drop is the one gesture jsdom cannot make: dnd-kit measures rectangles,
 * and every rectangle here is zero. The context is wrapped to hand the test
 * the `onDragEnd` the launcher gave it, so what is checked is what the
 * launcher does with a finished drag — the tiles' new order and its memory.
 */
const dnd = vi.hoisted(() => ({
  handlers: [] as Array<((event: DragEndEvent) => void) | undefined>,
}));

vi.mock("@dnd-kit/core", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@dnd-kit/core")>();
  return {
    ...actual,
    DndContext: (props: ComponentProps<typeof actual.DndContext>) => {
      dnd.handlers.push(props.onDragEnd);
      return <actual.DndContext {...props} />;
    },
  };
});

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn(), loading: vi.fn() },
}));

const org: Organization = {
  can_send_email: false,
  timezone: "UTC",
  currency: "PLN",
  id: "org-1",
  name: "Test",
  created_at: new Date().toISOString(),
  created_by: null,
  settings: null,
  active_profile_id: null,
  onboarding_completed: true,
};

function mod(
  name: string,
  category: LauncherCategory,
  displayName: string,
): FrontendModule {
  return {
    name,
    routes: [{ path: `/${name}`, component: () => null }],
    launcher: { displayName, icon: Home, category },
  };
}

function drag(activeId: string, overId: string | null) {
  const handler = dnd.handlers.at(-1);
  if (!handler) throw new Error("the launcher mounted no sortable grid");
  act(() =>
    handler({
      active: { id: activeId },
      over: overId === null ? null : { id: overId },
    } as DragEndEvent),
  );
}

/** Where the tiles of the (last) desktop grid lead, in order. */
function desktopOrder(container: HTMLElement): string[] {
  const grids = container.querySelectorAll<HTMLElement>("ul[role='list']");
  const desktop = grids[grids.length - 1];
  return within(desktop)
    .getAllByRole("link")
    .map((link) => link.getAttribute("href") ?? "")
    .filter((href) => href !== "/apps");
}

function renderLauncher() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <ModulesProvider>
        <MemoryRouter>
          <Launcher />
        </MemoryRouter>
      </ModulesProvider>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  localStorage.clear();
  forgetFirstVisits();
  dnd.handlers.length = 0;
  // Three tiles under three headings collapse into one sortable grid.
  moduleRegistry.getVisibleModules = vi.fn(() => [
    mod("inventory", "core", "inventory:launcher.title"),
    mod("webhooks", "business", "webhooks:title"),
    mod("stats", "analytics", "stats:title"),
  ]);
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
    http.get("*/api/v1/profiles", () => HttpResponse.json(onePage([]))),
    http.get("*/api/v1/organizations/my", () => HttpResponse.json(org)),
    http.get("*/api/v1/modules/my", () =>
      HttpResponse.json(["inventory", "webhooks", "stats"]),
    ),
  );
});

describe("Launcher — dropping a tile", () => {
  it("puts the tile where it was dropped and keeps it there on the next visit", async () => {
    const first = renderLauncher();
    await screen.findAllByRole("link", { name: /^Statistics/ });
    expect(desktopOrder(first.container).slice(0, 3)).toEqual([
      "/inventory",
      "/webhooks",
      "/stats",
    ]);

    drag("stats", "inventory");

    await waitFor(() =>
      expect(desktopOrder(first.container).slice(0, 3)).toEqual([
        "/stats",
        "/inventory",
        "/webhooks",
      ]),
    );
    first.unmount();

    const second = renderLauncher();
    await screen.findAllByRole("link", { name: /^Statistics/ });
    expect(desktopOrder(second.container).slice(0, 3)).toEqual([
      "/stats",
      "/inventory",
      "/webhooks",
    ]);
  });

  it("changes nothing when the tile is dropped outside any tile or back on itself", async () => {
    const { container } = renderLauncher();
    await screen.findAllByRole("link", { name: /^Statistics/ });

    drag("stats", null);
    drag("stats", "stats");

    expect(desktopOrder(container).slice(0, 3)).toEqual([
      "/inventory",
      "/webhooks",
      "/stats",
    ]);
    expect(
      Object.keys(localStorage).filter((k) =>
        k.startsWith("launcher_tile_order"),
      ),
    ).toEqual([]);
  });
});
