import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { http, HttpResponse } from "msw";
import { server } from "@/test/mocks/server";
import { moduleRegistry, type FrontendModule } from "@/lib/moduleRegistry";
import { useAuthStore } from "@/store/authStore";
import { ModulesProvider } from "@/contexts/ModulesContext";
import Launcher from "./Launcher";
import { addRecentItem } from "@/lib/recentItems";
import { forgetFirstVisits } from "../hooks/useLauncherGreeting";
import type { ProductProfile, Organization, LauncherCategory } from "@/types";
import { Home } from "lucide-react";
import { onePage } from "@/test/mocks/page";
import { signInWith } from "@/test/auth";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn(), loading: vi.fn() },
}));

const profile: ProductProfile = {
  id: "food_home",
  name: "Food & Home",
  description: "",
  default_modules: ["inventory"],
  seed_profile: "food_home",
  launcher_categories: {
    inventory: "business",
  },
};

const org: Organization = {
  can_send_email: false,
  timezone: "UTC",
  currency: "PLN",
  id: "org-1",
  name: "Test",
  created_at: new Date().toISOString(),
  created_by: null,
  settings: null,
  active_profile_id: "food_home",
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

/** The tile grids, in DOM order: mobile first, then the desktop sections. */
function tileGrids(container: HTMLElement): HTMLElement[] {
  return Array.from(container.querySelectorAll("ul[role='list']"));
}

/** Where each tile in a grid leads, in order — one per tile, whatever it says. */
function tileTargets(grid: HTMLElement): string[] {
  return within(grid)
    .queryAllByRole("link")
    .map((link) => link.getAttribute("href") ?? "");
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
  // Reset registry between tests
  moduleRegistry.getVisibleModules = vi.fn(() => [
    mod("inventory", "core", "inventory:launcher.title"),
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
    http.get("*/api/v1/profiles", () => HttpResponse.json(onePage([profile]))),
    http.get("*/api/v1/organizations/my", () => HttpResponse.json(org)),
    http.get("*/api/v1/modules/my", () =>
      HttpResponse.json([
        "inventory",
        "core",
        "items",
        "locations",
        "categories",
      ]),
    ),
  );
});

describe("Launcher (profile-aware)", () => {
  it("puts a module in the section its active profile names", async () => {
    // Two modules per section, so the sections have something to group and
    // the headings render at all.
    moduleRegistry.getVisibleModules = vi.fn(() => [
      mod("inventory", "core", "inventory:launcher.title"),
      mod("webhooks", "business", "webhooks:title"),
      mod("api_keys", "business", "api_keys:title"),
      mod("stats", "analytics", "stats:title"),
    ]);
    server.use(
      http.get("*/api/v1/profiles", () =>
        HttpResponse.json(
          onePage([
            {
              ...profile,
              launcher_categories: {
                inventory: "business",
                stats: "analytics",
              },
            },
          ]),
        ),
      ),
    );
    renderLauncher();

    await waitFor(() => {
      expect(screen.getByText("Business")).toBeInTheDocument();
    });
    // The profile moved inventory out of Essentials, leaving that section empty.
    expect(screen.queryByText("Essentials")).not.toBeInTheDocument();

    const links = await screen.findAllByRole("link", { name: /^Inventory/ });
    expect(links[0]).toHaveAttribute("href", "/inventory");
  });

  it("names the Essentials section in the language of the product, not the architecture", async () => {
    moduleRegistry.getVisibleModules = vi.fn(() => [
      mod("inventory", "core", "inventory:launcher.title"),
      mod("items", "core", "webhooks:title"),
      mod("stats", "analytics", "stats:title"),
      mod("api_keys", "analytics", "api_keys:title"),
    ]);
    server.use(
      http.get("*/api/v1/organizations/my", () =>
        HttpResponse.json({ ...org, active_profile_id: null }),
      ),
    );
    renderLauncher();

    await waitFor(() => {
      expect(screen.getByText("Essentials")).toBeInTheDocument();
    });
    expect(screen.queryByText("Core")).not.toBeInTheDocument();
  });

  it("drops the headings when they would outnumber what they organize", async () => {
    // Three tiles under three headings: every heading covers a single tile,
    // so the grouping organizes nothing.
    moduleRegistry.getVisibleModules = vi.fn(() => [
      mod("inventory", "core", "inventory:launcher.title"),
      mod("webhooks", "business", "webhooks:title"),
      mod("stats", "analytics", "stats:title"),
    ]);
    server.use(
      http.get("*/api/v1/organizations/my", () =>
        HttpResponse.json({ ...org, active_profile_id: null }),
      ),
    );
    const { container } = renderLauncher();

    await screen.findAllByRole("link", { name: /^Statistics/ });
    expect(screen.queryByText("Essentials")).not.toBeInTheDocument();
    expect(screen.queryByText("Business")).not.toBeInTheDocument();
    expect(screen.queryByText("Analytics")).not.toBeInTheDocument();
    // One mobile grid, one desktop grid — not one grid per category.
    expect(tileGrids(container)).toHaveLength(2);
  });

  it("shows the same arrangement on both form factors", async () => {
    moduleRegistry.getVisibleModules = vi.fn(() => [
      mod("inventory", "core", "inventory:launcher.title"),
      mod("webhooks", "business", "webhooks:title"),
      mod("stats", "analytics", "stats:title"),
    ]);
    // An arrangement made by dragging on a wide screen.
    localStorage.setItem(
      "launcher_tile_order:default:user-1:all",
      JSON.stringify(["stats", "inventory", "webhooks"]),
    );
    server.use(
      http.get("*/api/v1/organizations/my", () =>
        HttpResponse.json({ ...org, active_profile_id: null }),
      ),
    );
    const { container } = renderLauncher();

    await screen.findAllByRole("link", { name: /^Statistics/ });
    const [mobile, desktop] = tileGrids(container);
    expect(tileTargets(mobile).slice(0, 3)).toEqual([
      "/stats",
      "/inventory",
      "/webhooks",
    ]);
    expect(tileTargets(desktop).slice(0, 3)).toEqual(
      tileTargets(mobile).slice(0, 3),
    );
  });

  it("does not announce a tile as sortable when nothing describes how to sort it", async () => {
    const { container } = renderLauncher();
    await screen.findAllByRole("link", { name: /^Inventory/ });

    const sortable = container.querySelectorAll(
      "[aria-roledescription='sortable']",
    );
    // The desktop grid still sorts — this is not a test that drag was removed.
    expect(sortable.length).toBe(1);
    for (const el of sortable) {
      const describedBy = el.getAttribute("aria-describedby");
      expect(describedBy).toBeTruthy();
      expect(document.getElementById(describedBy!)).not.toBeNull();
    }
  });

  it("starts the drag from the node that announces itself as sortable", async () => {
    const { container } = renderLauncher();
    await screen.findAllByRole("link", { name: /^Inventory/ });

    // The reader lands on a node that says "sortable" and carries the
    // instruction "press the space bar". That promise is kept only where the
    // attributes and the listeners sit on the same node: measured on the
    // running app, the attributes were on this node and the listeners on the
    // link inside it, so the space bar did nothing on the node that announced
    // it and the reader had to tab once more onto an undeclared handle.
    const announced = container.querySelector<HTMLElement>(
      "[aria-roledescription='sortable']",
    );
    expect(announced).not.toBeNull();

    fireEvent.keyDown(announced!, { code: "Space" });
    await waitFor(() =>
      expect(
        document.querySelector('[id^="DndLiveRegion"]')?.textContent,
      ).toContain("Inventory"),
    );
    fireEvent.keyDown(announced!, { code: "Escape" });
  });

  /**
   * The drag attributes made the `<li>` a `role="button"` with the tile's
   * link inside it: two tab stops per tile, an interactive element nested in
   * another (axe nested-interactive), and a `role="list"` holding buttons
   * instead of list items (aria-required-children). The link is the handle.
   */
  it("keeps one interactive element per tile in a list of list items", async () => {
    const { container } = renderLauncher();
    await screen.findAllByRole("link", { name: /^Inventory/ });

    for (const grid of tileGrids(container)) {
      for (const child of Array.from(grid.children)) {
        expect(child.tagName).toBe("LI");
        expect(child).not.toHaveAttribute("role");
        expect(child).not.toHaveAttribute("tabindex");
      }
    }
    const sortable = container.querySelectorAll(
      "[aria-roledescription='sortable']",
    );
    expect(sortable).toHaveLength(1);
    expect(sortable[0].tagName).toBe("A");
    expect(sortable[0]).toHaveAttribute("role", "link");
    expect(sortable[0]).not.toHaveAttribute("aria-pressed");
  });

  it("opens a tile with Enter and leaves picking it up to the space bar", async () => {
    const { container } = renderLauncher();
    await screen.findAllByRole("link", { name: /^Inventory/ });
    const tile = container.querySelector<HTMLElement>(
      "a[aria-roledescription='sortable']",
    )!;

    // `fireEvent` answers false when a handler called preventDefault — what
    // a drag that starts on Enter does, and what stops the link opening.
    expect(fireEvent.keyDown(tile, { code: "Enter", key: "Enter" })).toBe(true);
    expect(
      document.querySelector('[id^="DndLiveRegion"]')?.textContent ?? "",
    ).not.toContain("Inventory");
  });

  it("renders the Browse Apps tile with a /apps link when user is admin", async () => {
    renderLauncher();
    const links = await screen.findAllByRole("link", { name: /browse apps/i });
    expect(links.length).toBeGreaterThan(0);
    expect(links[0]).toHaveAttribute("href", "/apps");
  });

  it("gives the sidebar no width when it has nothing to show", async () => {
    renderLauncher();
    await screen.findAllByRole("link", { name: /^Inventory/ });

    const sidebar = screen.getByTestId("launcher-sidebar");
    // `empty:hidden` only collapses a genuinely childless element, so the
    // assertion is on the DOM, not on the class alone.
    expect(sidebar.childElementCount).toBe(0);
    expect(sidebar.className).toContain("empty:hidden");
  });
});

describe("Launcher status badges", () => {
  // What a module's badge hook answers when its endpoint refuses the read.
  const refused = { count: 0, labelKey: "widgets:statusBadge", failed: true };

  function badgedModule(useStatusBadge: () => typeof refused) {
    return {
      ...mod("widgets", "core", "Widgets"),
      useStatusBadge,
      statusBadgePermission: "widgets:read",
    };
  }

  it("does not ask the status of a module whose read the role does not hold", async () => {
    // A custom role holding one module's read was asked every other enabled
    // module's status, met a 403 on each, and every such tile said its status
    // could not be read. The tile stays; its status is not asked.
    const useStatusBadge = vi.fn(() => refused);
    moduleRegistry.getVisibleModules = vi.fn(() => [
      badgedModule(useStatusBadge),
    ]);
    signInWith(["warehouse:read"]);
    renderLauncher();

    expect(
      (await screen.findAllByRole("link", { name: /^Widgets/ })).length,
    ).toBeGreaterThan(0);
    expect(useStatusBadge).not.toHaveBeenCalled();
    expect(
      screen.queryByText(/Status could not be read/),
    ).not.toBeInTheDocument();
  });

  it("asks the status of a role holding the read the module names", async () => {
    const useStatusBadge = vi.fn(() => refused);
    moduleRegistry.getVisibleModules = vi.fn(() => [
      badgedModule(useStatusBadge),
    ]);
    signInWith(["widgets:read"]);
    renderLauncher();

    expect(
      (await screen.findAllByText(/Status could not be read/)).length,
    ).toBeGreaterThan(0);
    expect(useStatusBadge).toHaveBeenCalled();
  });
});

describe("Launcher recently visited", () => {
  it("names the module the way its tile does, not by its technical name", async () => {
    // "Recently visited" printed the stored module identifier ("shopping_lists")
    // beside a tile and a palette that both said "Shopping lists".
    moduleRegistry.getVisibleModules = vi.fn(() => [
      mod("inventory", "core", "inventory:launcher.title"),
    ]);
    addRecentItem(
      {
        id: "r1",
        title: "Oat milk",
        module: "inventory",
        path: "/inventory/items/1",
        timestamp: 0,
      },
      "user-1",
      "default",
    );
    renderLauncher();

    const link = await screen.findByRole("link", { name: /Oat milk/ });
    expect(link).toHaveTextContent("Inventory");
    expect(link).not.toHaveTextContent("inventory");
  });
});

describe("Launcher greeting", () => {
  const joined: Organization = { ...org, name: "Acme Pantry" };
  const useJoinedOrg = () =>
    server.use(
      http.get("*/api/v1/organizations/my", () => HttpResponse.json(joined)),
    );

  it("welcomes a first visit without assuming an earlier one and names the organization", async () => {
    // The title used to be "Welcome back" for anyone whose name was known,
    // forty seconds after the account was made, and the screen never said
    // which organization the person had just joined.
    useJoinedOrg();
    renderLauncher();

    const heading = await screen.findByRole("heading", { level: 1 });
    expect(heading).toHaveTextContent("Welcome, Test");
    expect(heading).not.toHaveTextContent("back");
    expect(await screen.findByText(/Acme Pantry/)).toBeInTheDocument();
  });

  it("tells the founder they set the organization up, not that they joined it", async () => {
    // Registration creates the organization for the first account; greeting
    // its founder with "You have joined" named a step they never took.
    server.use(
      http.get("*/api/v1/organizations/my", () =>
        HttpResponse.json({ ...joined, created_by: "user-1" }),
      ),
    );
    renderLauncher();

    expect(
      await screen.findByText(/You set up Acme Pantry/),
    ).toBeInTheDocument();
    expect(screen.queryByText(/You have joined/)).not.toBeInTheDocument();
  });

  it("says welcome back from the second visit on", async () => {
    useJoinedOrg();
    const first = renderLauncher();
    await screen.findByText(/Acme Pantry/);
    first.unmount();
    forgetFirstVisits(); // the next page load

    renderLauncher();

    expect(await screen.findByRole("heading", { level: 1 })).toHaveTextContent(
      "Welcome back, Test",
    );
  });

  it("keeps the first-visit welcome when the page re-renders within the visit", async () => {
    useJoinedOrg();
    const view = renderLauncher();
    await screen.findByText(/Acme Pantry/);

    view.rerender(
      <QueryClientProvider client={new QueryClient()}>
        <ModulesProvider>
          <MemoryRouter>
            <Launcher />
          </MemoryRouter>
        </ModulesProvider>
      </QueryClientProvider>,
    );

    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent(
      "Welcome, Test",
    );
  });

  it("does not count a launcher mount that happens before onboarding as the visit", async () => {
    // On a first login the launcher can mount while the organization is still
    // open for onboarding, just before the person is sent there. The welcome
    // that names the organization comes after onboarding, and it must still
    // be the first one.
    server.use(
      http.get("*/api/v1/organizations/my", () =>
        HttpResponse.json({ ...joined, onboarding_completed: false }),
      ),
    );
    const before = renderLauncher();
    await screen.findByRole("heading", { level: 1 });
    await waitFor(() =>
      expect(screen.getByRole("heading", { level: 1 })).toBeInTheDocument(),
    );
    before.unmount();

    useJoinedOrg();
    renderLauncher();

    expect(await screen.findByRole("heading", { level: 1 })).toHaveTextContent(
      "Welcome, Test",
    );
    expect(
      await screen.findByText(/You have joined Acme Pantry/),
    ).toBeInTheDocument();
  });

  it("does not count a mount that is gone before the organization has loaded", async () => {
    let release: () => void = () => {};
    const gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    server.use(
      http.get("*/api/v1/organizations/my", async () => {
        await gate;
        return HttpResponse.json(joined);
      }),
    );
    const early = renderLauncher();
    await screen.findByRole("heading", { level: 1 });
    early.unmount();
    release();

    useJoinedOrg();
    renderLauncher();

    expect(await screen.findByRole("heading", { level: 1 })).toHaveTextContent(
      "Welcome, Test",
    );
  });

  it("keeps the welcome when the launcher is remounted within the visit", async () => {
    // Finishing onboarding changes the enabled modules, which rebuilds the
    // router and mounts the launcher again straight away. The remount must not
    // find the visit already spent by the mount it replaced.
    useJoinedOrg();
    const first = renderLauncher();
    await screen.findByText(/You have joined Acme Pantry/);
    await waitFor(() =>
      expect(localStorage.getItem("inventari:greeted:user-1")).toBe("true"),
    );
    first.unmount();

    renderLauncher();

    expect(await screen.findByRole("heading", { level: 1 })).toHaveTextContent(
      "Welcome, Test",
    );
    expect(
      await screen.findByText(/You have joined Acme Pantry/),
    ).toBeInTheDocument();
  });
});
