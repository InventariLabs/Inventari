import {
  render,
  screen,
  fireEvent,
  waitFor,
  within,
} from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { BrowserRouter, MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import AppStore from "./AppStore";
import { server } from "@/test/mocks/server";
import { http, HttpResponse } from "msw";
import { withLanguage, tFor } from "@/test/mocks/i18n";
import { toast } from "sonner";
import * as modulesCtx from "@/contexts/ModulesContext";
import { onePage } from "@/test/mocks/page";

// Admin: AppStore redirects non-admins away before rendering anything.
const mockAuthState = {
  user: { role: "admin", is_superuser: false },
  isAuthenticated: true,
  isLoading: false,
};
vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn(), loading: vi.fn() },
}));

vi.mock("@/store/authStore", () => ({
  useAuthStore: (selector?: (s: typeof mockAuthState) => unknown) =>
    selector ? selector(mockAuthState) : mockAuthState,
}));

const Wrapper = ({ children }: { children: React.ReactNode }) => (
  <QueryClientProvider
    client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
  >
    <BrowserRouter>{children}</BrowserRouter>
  </QueryClientProvider>
);

describe("AppStore search", () => {
  beforeEach(() => {
    vi.spyOn(modulesCtx, "useModules").mockReturnValue({
      enabledModules: [],
      isModuleEnabled: () => false,
      isLoading: false,
      refreshModules: vi.fn(),
      focusModule: null,
      hiddenModules: [],
    });
    server.use(
      http.get("/api/v1/modules/available", () =>
        HttpResponse.json(
          onePage([
            {
              name: "maker",
              display_name: "Maker",
              description:
                "Bill of Materials, production runs and cost rollup for makers and micro-manufacturers.",
              icon: "factory",
              requires: [],
              version: "1.0.0",
              requires_api_key: false,
            },
          ]),
        ),
      ),
    );
  });

  it("makes every module tile a second-level heading", async () => {
    render(<AppStore />, { wrapper: Wrapper });

    // The tiles used to be h3 under the shell's h1 — a heading level skipped
    // in between, so the tree read as if a section were missing.
    expect(
      (await screen.findAllByRole("heading", { level: 2 })).length,
    ).toBeGreaterThan(0);
    expect(screen.queryByRole("heading", { level: 3 })).toBeNull();
  });

  it("finds a module by its translated name and by its technical name", async () => {
    await withLanguage("pl", async () => {
      render(<AppStore />, { wrapper: Wrapper });
      // The tile shows the Polish name from modules.json.
      expect(await screen.findByText("Produkcja")).toBeInTheDocument();

      const search = screen.getByPlaceholderText(
        tFor("common")("appStore.searchPlaceholder"),
      );

      // Translated label is searchable.
      fireEvent.change(search, { target: { value: "produkcja" } });
      expect(screen.getByText("Produkcja")).toBeInTheDocument();

      // Technical name stays searchable on purpose.
      fireEvent.change(search, { target: { value: "maker" } });
      expect(screen.getByText("Produkcja")).toBeInTheDocument();

      // A non-matching query filters the tile out.
      fireEvent.change(search, { target: { value: "zzzz" } });
      expect(screen.queryByText("Produkcja")).not.toBeInTheDocument();
    });
  });
});

describe("AppStore card status", () => {
  beforeEach(() => {
    vi.spyOn(modulesCtx, "useModules").mockReturnValue({
      enabledModules: [],
      isModuleEnabled: () => false,
      isLoading: false,
      refreshModules: vi.fn(),
      focusModule: null,
      hiddenModules: [],
    });
    server.use(
      http.get("/api/v1/modules/available", () =>
        HttpResponse.json(
          onePage([
            {
              name: "webhooks",
              display_name: "Webhooks",
              description: "Sends events outward.",
              icon: "webhook",
              requires: [],
              version: "1.0.0",
              requires_api_key: false,
              module_type: "core",
              capabilities: ["database", "network"],
            },
          ]),
        ),
      ),
    );
  });

  it("says on the card that a module is switched off", async () => {
    await withLanguage("en", async () => {
      render(<AppStore />, { wrapper: Wrapper });

      expect(await screen.findByText("Webhooks")).toBeInTheDocument();
      // Switching off used to take the "Enabled" badge away and put nothing
      // in its place: the card's state lived only in the button label, which
      // reads the same on every card.
      expect(screen.getAllByText("Disabled").length).toBeGreaterThan(0);
    });
  });
});

describe("AppStore trust badges", () => {
  beforeEach(() => {
    vi.spyOn(modulesCtx, "useModules").mockReturnValue({
      enabledModules: [],
      isModuleEnabled: () => false,
      isLoading: false,
      refreshModules: vi.fn(),
      focusModule: null,
      hiddenModules: [],
    });
    server.use(
      http.get("/api/v1/modules/available", () =>
        HttpResponse.json(
          onePage([
            {
              name: "webhooks",
              display_name: "Webhooks",
              description: "Sends events outward.",
              icon: "webhook",
              requires: [],
              version: "1.0.0",
              requires_api_key: false,
              module_type: "core",
              is_always_on: true,
              capabilities: ["database", "network"],
            },
            {
              name: "api_keys",
              display_name: "API Keys",
              description: "Access tokens for scripts.",
              icon: "key",
              requires: [],
              version: "1.0.0",
              requires_api_key: false,
              module_type: "core",
              capabilities: ["database"],
            },
            {
              name: "integrator",
              display_name: "Integrator",
              description: "An outside module.",
              icon: "box",
              requires: [],
              version: "0.1.0",
              requires_api_key: false,
              module_type: "community",
              capabilities: [],
            },
          ]),
        ),
      ),
    );
  });

  it("badges every trust level, the base level included", async () => {
    await withLanguage("en", async () => {
      render(<AppStore />, { wrapper: Wrapper });

      expect(await screen.findByText("Webhooks")).toBeInTheDocument();
      // `community` is the base level and still draws its badge: the row
      // carries badges unrelated to trust beside it, so a card without a
      // trust badge reads as a badge that failed to load, not as a level.
      expect(screen.getByText("Core")).toBeInTheDocument();
      expect(screen.getByText("Community")).toBeInTheDocument();
    });
  });

  it("draws Deactivate as a button on the tinted card of a module that is on", async () => {
    // The raised fill all but vanished on that tint: the word sat on the card
    // like plain text beside a solid Activate on the cards that are off.
    vi.spyOn(modulesCtx, "useModules").mockReturnValue({
      enabledModules: ["api_keys"],
      isModuleEnabled: (name: string) => name === "api_keys",
      isLoading: false,
      refreshModules: vi.fn(),
      focusModule: null,
      hiddenModules: [],
    });
    render(<AppStore />, { wrapper: Wrapper });

    const deactivate = await screen.findByRole("button", {
      name: tFor("common")("appStore.deactivate"),
    });
    expect(deactivate).toHaveClass("border", "border-border");
  });

  it("does not badge a module Core while it can be switched off", async () => {
    await withLanguage("en", async () => {
      render(<AppStore />, { wrapper: Wrapper });

      // "Core" means always on everywhere else on the page: only the card
      // that is always on wears it, the switchable one is Official.
      const switchable = (await screen.findByText("API Keys")).closest(
        "div[class*='flex']",
      )?.parentElement as HTMLElement;
      expect(within(switchable).getByText("Official")).toBeInTheDocument();
      expect(within(switchable).queryByText("Core")).toBeNull();
      expect(screen.getAllByText("Core")).toHaveLength(1);
    });
  });
});

describe("AppStore refusals", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.spyOn(modulesCtx, "useModules").mockReturnValue({
      enabledModules: ["maker"],
      isModuleEnabled: (name: string) => name === "maker",
      isLoading: false,
      refreshModules: vi.fn(),
      focusModule: null,
      hiddenModules: [],
    });
    server.use(
      http.get("/api/v1/modules/available", () =>
        HttpResponse.json(
          onePage([
            {
              name: "maker",
              display_name: "Maker",
              description: "Production runs.",
              icon: "factory",
              requires: [],
              version: "1.0.0",
              requires_api_key: false,
            },
          ]),
        ),
      ),
    );
  });

  it("repeats the server's reason instead of a generic sentence", async () => {
    // The empty `catch` swallowed "Module 'printing' is always enabled and
    // cannot be turned off" and printed "update failed" — so the reader kept
    // pressing a button that could not work.
    server.use(
      http.post("/api/v1/modules/toggle", () =>
        HttpResponse.json(
          {
            detail: {
              code: "FORBIDDEN",
              message:
                "Module 'maker' is always enabled and cannot be turned off.",
            },
          },
          { status: 403 },
        ),
      ),
    );

    await withLanguage("pl", async () => {
      render(<AppStore />, { wrapper: Wrapper });
      const tile = await screen.findByText("Produkcja");
      const card = tile.closest("div[class*='rounded']") ?? tile.parentElement!;
      const toggle = card.querySelector("button");
      fireEvent.click(toggle!);

      // Every switch-off asks first; the refusal waits behind the answer.
      const dialog = await screen.findByRole("alertdialog");
      fireEvent.click(
        within(dialog).getByRole("button", { name: /dezaktywuj/i }),
      );

      await waitFor(() =>
        expect(toast.error).toHaveBeenCalledWith(
          "Module 'maker' is always enabled and cannot be turned off.",
        ),
      );
    });
  });
});

describe("AppStore taxonomy", () => {
  const t = tFor("common");

  function withCatalog(modules: Record<string, unknown>[]) {
    server.use(
      http.get("/api/v1/modules/available", () =>
        HttpResponse.json(onePage(modules)),
      ),
    );
  }

  beforeEach(() => {
    vi.clearAllMocks();
    mockAuthState.user = { role: "admin", is_superuser: false };
    vi.spyOn(modulesCtx, "useModules").mockReturnValue({
      enabledModules: ["stats"],
      isModuleEnabled: (name: string) => name === "stats",
      isLoading: false,
      refreshModules: vi.fn(),
      focusModule: null,
      hiddenModules: [],
    });
  });

  const statsModule = {
    name: "stats",
    display_name: "Statistics",
    description: "Consumption analysis.",
    icon: "bar-chart-3",
    category: "analytics",
    requires: [],
    version: "1.0.0",
    requires_api_key: false,
    is_always_on: true,
  };

  const visionModule = {
    name: "vision",
    display_name: "Photo Recognition",
    description: "Recognise products from photos.",
    icon: "camera",
    category: "integrations",
    requires: [],
    version: "1.0.0",
    requires_api_key: true,
    degraded: true,
  };

  // The filter set renders twice — a scrolling row on a phone, a sidebar
  // from `lg:` up — so a filter is two buttons with one name.
  const filters = (name: string) => screen.queryAllByRole("button", { name });
  const findFilter = async (name: string) =>
    (await screen.findAllByRole("button", { name }))[0];

  it("offers only the categories something is in", async () => {
    // Eight filters, three of which matched nothing: Core, Analytics and
    // System all answered "No modules found" — the sentence a failed search
    // gets — because the category came off the launcher tile and six modules
    // have none.
    withCatalog([statsModule, visionModule]);
    render(<AppStore />, { wrapper: Wrapper });

    expect(
      await findFilter(t("appStore.categoryAnalytics")),
    ).toBeInTheDocument();
    expect(filters(t("appStore.categoryIntegrations"))).not.toHaveLength(0);
    expect(filters(t("appStore.categoryCore"))).toHaveLength(0);
    expect(filters(t("appStore.categorySystem"))).toHaveLength(0);
  });

  it("says which filter is the chosen one", async () => {
    // The state used to be carried by the background colour alone.
    withCatalog([statsModule, visionModule]);
    render(<AppStore />, { wrapper: Wrapper });

    const analytics = await findFilter(t("appStore.categoryAnalytics"));
    expect(analytics).toHaveAttribute("aria-pressed", "false");
    fireEvent.click(analytics);
    expect(analytics).toHaveAttribute("aria-pressed", "true");
  });

  it("groups a module by the category the API sends", async () => {
    withCatalog([statsModule, visionModule]);
    render(<AppStore />, { wrapper: Wrapper });

    fireEvent.click(await findFilter(t("appStore.categoryAnalytics")));

    expect(screen.getByText("Statistics")).toBeInTheDocument();
    expect(screen.queryByText("Photo Recognition")).not.toBeInTheDocument();
  });

  it("does not offer to switch off a module the server will not switch off", async () => {
    // `Statistics` and `Label Printing` had a Deactivate button that could
    // only ever come back 403, because "required" was read off the launcher
    // tile rather than from `is_always_on`.
    withCatalog([statsModule]);
    render(<AppStore />, { wrapper: Wrapper });

    expect(await screen.findByText("Statistics")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: t("appStore.deactivate") }),
    ).not.toBeInTheDocument();
    expect(screen.getByText(t("appStore.alwaysOnHint"))).toBeInTheDocument();
  });

  it("says a module will run short before it is switched on", async () => {
    // `nutrition` comes back `degraded: true` and its card looked like every
    // other one.
    withCatalog([visionModule]);
    render(<AppStore />, { wrapper: Wrapper });

    expect(
      await screen.findByText(t("appStore.degradedHint")),
    ).toBeInTheDocument();
    expect(screen.getByText(t("appStore.needsApiKeyHint"))).toBeInTheDocument();
  });
});

describe("AppStore optional companions", () => {
  const t = tFor("common");
  const mt = tFor("modules");

  // recipes integrates with shopping_lists without depending on it — the one
  // soft edge the platform declares.
  const shoppingListsModule = {
    name: "shopping_lists",
    display_name: "Shopping Lists",
    description: "Shopping lists.",
    icon: "list",
    category: "business",
    requires: [],
    version: "1.0.0",
    requires_api_key: false,
  };

  const recipesModule = {
    name: "recipes",
    display_name: "Recipes",
    description: "Recipe management.",
    icon: "chef-hat",
    category: "business",
    requires: [],
    optional_requires: ["shopping_lists"],
    version: "1.0.0",
    requires_api_key: false,
  };

  const hintWith = (names: string) =>
    t("appStore.optionalCompanionsHint", { names });

  function withEnabled(enabled: string[]) {
    vi.spyOn(modulesCtx, "useModules").mockReturnValue({
      enabledModules: enabled,
      isModuleEnabled: (name: string) => enabled.includes(name),
      isLoading: false,
      refreshModules: vi.fn(),
      focusModule: null,
      hiddenModules: [],
    });
    server.use(
      http.get("/api/v1/modules/available", () =>
        HttpResponse.json(onePage([recipesModule, shoppingListsModule])),
      ),
    );
  }

  beforeEach(() => {
    vi.clearAllMocks();
    mockAuthState.user = { role: "admin", is_superuser: false };
  });

  it("names the switched-off companion before the decision", async () => {
    withEnabled([]);
    render(<AppStore />, { wrapper: Wrapper });

    expect(
      await screen.findByText(hintWith(mt("modules.shopping_lists.name"))),
    ).toBeInTheDocument();
  });

  it("says nothing when the companion is already on", async () => {
    withEnabled(["shopping_lists"]);
    render(<AppStore />, { wrapper: Wrapper });

    await screen.findByText(mt("modules.recipes.name"));
    expect(
      screen.queryByText(hintWith(mt("modules.shopping_lists.name"))),
    ).not.toBeInTheDocument();
  });

  it("names the switched-off companion on a module that is already on", async () => {
    // A module running without its companion is where the gap matters most:
    // the card says why part of it is missing, in the present tense.
    withEnabled(["recipes"]);
    render(<AppStore />, { wrapper: Wrapper });

    const names = mt("modules.shopping_lists.name");
    expect(
      await screen.findByText(
        t("appStore.optionalCompanionsOffHint", { names }),
      ),
    ).toBeInTheDocument();
    expect(screen.queryByText(hintWith(names))).not.toBeInTheDocument();
  });

  it("lists several switched-off companions without agreeing with them", async () => {
    // The hint holds a list of names; a verb or pronoun agreeing with it is
    // wrong as soon as there are two ("Approvals, Purchase Orders is …").
    const stub = (name: string, extra = {}) => ({
      name,
      display_name: name,
      description: "x",
      icon: "box",
      category: "business",
      requires: [],
      version: "1.0.0",
      requires_api_key: false,
      ...extra,
    });
    vi.spyOn(modulesCtx, "useModules").mockReturnValue({
      enabledModules: ["warehouse"],
      isModuleEnabled: (name: string) => name === "warehouse",
      isLoading: false,
      refreshModules: vi.fn(),
      focusModule: null,
      hiddenModules: [],
    });
    server.use(
      http.get("/api/v1/modules/available", () =>
        HttpResponse.json(
          onePage([
            stub("warehouse", {
              optional_requires: ["approvals", "purchase_orders"],
            }),
            stub("approvals"),
            stub("purchase_orders"),
          ]),
        ),
      ),
    );
    render(<AppStore />, { wrapper: Wrapper });

    const names = `${mt("modules.approvals.name")}, ${mt("modules.purchase_orders.name")}`;
    const hint = t("appStore.optionalCompanionsOffHint", { names });
    expect(await screen.findByText(hint)).toBeInTheDocument();
    // In English the old wording read "Approvals, Purchase Orders is not …".
    expect(hint).not.toMatch(/\{\{|\bis not\b|\bwith it\b/);
  });

  it("says nothing on a module that is on when its companion is on too", async () => {
    withEnabled(["recipes", "shopping_lists"]);
    render(<AppStore />, { wrapper: Wrapper });

    await screen.findByText(mt("modules.recipes.name"));
    expect(
      screen.queryByText(
        t("appStore.optionalCompanionsOffHint", {
          names: mt("modules.shopping_lists.name"),
        }),
      ),
    ).not.toBeInTheDocument();
  });

  it("says nothing for a module that declares no companions", async () => {
    withEnabled([]);
    server.use(
      http.get("/api/v1/modules/available", () =>
        HttpResponse.json(onePage([shoppingListsModule])),
      ),
    );
    render(<AppStore />, { wrapper: Wrapper });

    await screen.findByText(mt("modules.shopping_lists.name"));
    expect(
      screen.queryByText(hintWith(mt("modules.shopping_lists.name"))),
    ).not.toBeInTheDocument();
  });
});

describe("AppStore required modules", () => {
  const t = tFor("common");
  const mt = tFor("modules");

  // purchase_orders cannot be switched on without the warehouse: a hard
  // requirement, where a companion (above) is a soft one.
  const warehouseModule = {
    name: "warehouse",
    display_name: "Warehouse",
    description: "Receive and issue goods.",
    icon: "warehouse",
    category: "business",
    requires: [],
    version: "1.0.0",
    requires_api_key: false,
  };
  const purchaseOrdersModule = {
    name: "purchase_orders",
    display_name: "Purchase Orders",
    description: "Order from suppliers.",
    icon: "shopping-cart",
    category: "business",
    requires: ["warehouse"],
    version: "1.0.0",
    requires_api_key: false,
  };

  const requiresWith = (names: string) => t("appStore.requiresHint", { names });

  let toggled: boolean;

  function withEnabled(enabled: string[]) {
    vi.spyOn(modulesCtx, "useModules").mockReturnValue({
      enabledModules: enabled,
      isModuleEnabled: (name: string) => enabled.includes(name),
      isLoading: false,
      refreshModules: vi.fn(),
      focusModule: null,
      hiddenModules: [],
    });
    toggled = false;
    server.use(
      http.get("/api/v1/modules/available", () =>
        HttpResponse.json(onePage([purchaseOrdersModule, warehouseModule])),
      ),
      http.get("/api/v1/modules/:name/enable-preview", () =>
        HttpResponse.json({ resumes: 0 }),
      ),
      http.post("/api/v1/modules/toggle", () => {
        toggled = true;
        return HttpResponse.json({ success: true, enabled_modules: enabled });
      }),
    );
  }

  beforeEach(() => {
    vi.clearAllMocks();
    mockAuthState.user = { role: "admin", is_superuser: false };
  });

  it("names the switched-off requirement on the card, before the press", async () => {
    // The card said nothing, and the press answered "Module 'warehouse' must
    // be enabled first." — the slug of a card the store titles otherwise.
    withEnabled([]);
    await withLanguage("pl", async () => {
      render(<AppStore />, { wrapper: Wrapper });

      // "Magazyn": the card's own name for it, in the reader's language.
      expect(
        await screen.findByText(requiresWith(mt("modules.warehouse.name"))),
      ).toBeInTheDocument();
      expect(screen.queryByText(/warehouse/)).not.toBeInTheDocument();
    });
  });

  it("answers the press with that sentence instead of asking the server", async () => {
    withEnabled([]);
    render(<AppStore />, { wrapper: Wrapper });
    const hint = await screen.findByText(
      requiresWith(mt("modules.warehouse.name")),
    );
    const card = hint.closest("div[class*='rounded']")!;

    fireEvent.click(
      within(card as HTMLElement).getByRole("button", {
        name: t("appStore.activate"),
      }),
    );

    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith(
        requiresWith(mt("modules.warehouse.name")),
      ),
    );
    expect(toggled).toBe(false);
  });

  it("says nothing once the requirement is on", async () => {
    withEnabled(["warehouse"]);
    render(<AppStore />, { wrapper: Wrapper });

    await screen.findByText(mt("modules.purchase_orders.name"));
    expect(
      screen.queryByText(requiresWith(mt("modules.warehouse.name"))),
    ).not.toBeInTheDocument();
  });
});

describe("AppStore access", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.spyOn(modulesCtx, "useModules").mockReturnValue({
      enabledModules: [],
      isModuleEnabled: () => false,
      isLoading: false,
      refreshModules: vi.fn(),
      focusModule: null,
      hiddenModules: [],
    });
  });

  it("tells a member why, instead of bouncing them to the launcher", async () => {
    // `navigate("/", { replace: true })` inside an effect: the address changed
    // and nothing was said, so the reader had no idea the store even refused.
    mockAuthState.user = { role: "manager", is_superuser: false };

    render(<AppStore />, { wrapper: Wrapper });

    expect(
      await screen.findByText("This settings screen is for administrators"),
    ).toBeInTheDocument();

    mockAuthState.user = { role: "admin", is_superuser: false };
  });
});

describe("AppStore — arriving from somewhere that named a module", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockAuthState.user = { role: "admin", is_superuser: false };
    vi.spyOn(modulesCtx, "useModules").mockReturnValue({
      enabledModules: [],
      isModuleEnabled: () => false,
      isLoading: false,
      refreshModules: vi.fn(),
      focusModule: null,
      hiddenModules: [],
    });
    server.use(
      http.get("/api/v1/modules/available", () =>
        HttpResponse.json(
          onePage([
            {
              name: "partners",
              display_name: "Partners",
              description: "Suppliers and customers.",
              icon: "building-2",
              category: "business",
              requires: [],
              version: "1.0.0",
              requires_api_key: false,
            },
            {
              name: "maker",
              display_name: "Maker",
              description: "Production runs.",
              icon: "factory",
              category: "business",
              requires: [],
              version: "1.0.0",
              requires_api_key: false,
            },
          ]),
        ),
      ),
    );
  });

  it("opens on the module the link named instead of on all sixteen", async () => {
    // "Enable the Partners module" used to land on a page that did not mention
    // Partners, leaving the reader to find it among the tiles.
    render(
      <MemoryRouter initialEntries={["/apps?module=partners"]}>
        <AppStore />
      </MemoryRouter>,
      {
        wrapper: ({ children }: { children: React.ReactNode }) => (
          <QueryClientProvider
            client={
              new QueryClient({ defaultOptions: { queries: { retry: false } } })
            }
          >
            {children}
          </QueryClientProvider>
        ),
      },
    );

    expect(await screen.findByText("Partners")).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.queryByText("Maker")).not.toBeInTheDocument(),
    );
  });
});

describe("AppStore — who vouches for the author line", () => {
  /**
   * The author and the licence come off the package's own module.yaml. A
   * verified signature covers that file, so it turns them into something a
   * key stands behind; without one they are the package's own words, and
   * the card has to say which it is showing.
   */
  const pkg = (extra: Record<string, unknown>) => ({
    name: "maker",
    display_name: "Maker",
    description: "Bill of materials and production runs.",
    icon: "factory",
    requires: [],
    version: "1.0.0",
    requires_api_key: false,
    author: "Jan Kowalski",
    license: "MIT",
    ...extra,
  });

  beforeEach(() => {
    vi.spyOn(modulesCtx, "useModules").mockReturnValue({
      enabledModules: [],
      isModuleEnabled: () => false,
      isLoading: false,
      refreshModules: vi.fn(),
      focusModule: null,
      hiddenModules: [],
    });
  });

  it("names the key when the install verified a signature", async () => {
    server.use(
      http.get("/api/v1/modules/available", () =>
        HttpResponse.json(
          onePage([
            pkg({ signature_status: "verified", signed_by: "publisher-1" }),
          ]),
        ),
      ),
    );

    render(<AppStore />, { wrapper: Wrapper });

    expect(await screen.findByText(/publisher-1/)).toBeInTheDocument();
    expect(screen.getByText(/Jan Kowalski/)).toBeInTheDocument();
  });

  it("marks the identity as the package's own when nobody signed it", async () => {
    server.use(
      http.get("/api/v1/modules/available", () =>
        HttpResponse.json(onePage([pkg({ signature_status: "unsigned" })])),
      ),
    );

    render(<AppStore />, { wrapper: Wrapper });

    expect(
      await screen.findByText(tFor("common")("appStore.unsignedPackage")),
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        new RegExp(tFor("common")("appStore.declaredPrefix"), "i"),
      ),
    ).toBeInTheDocument();
  });

  it("says nothing about signatures for a module that came with the tree", async () => {
    server.use(
      http.get("/api/v1/modules/available", () =>
        HttpResponse.json(onePage([pkg({ author: "Core Team" })])),
      ),
    );

    render(<AppStore />, { wrapper: Wrapper });

    expect(
      await screen.findByText(new RegExp(tFor("common")("appStore.coreTeam"))),
    ).toBeInTheDocument();
    expect(
      screen.queryByText(tFor("common")("appStore.unsignedPackage")),
    ).not.toBeInTheDocument();
  });

  // The registry stamps "Core Team" on every module of the tree. It is a
  // registry value, not a name, so the card says it in the reader's language.
  it("translates the registry's author line for a module of the tree", async () => {
    server.use(
      http.get("/api/v1/modules/available", () =>
        HttpResponse.json(
          onePage([
            pkg({ author: "Core Team", module_type: "core", license: null }),
          ]),
        ),
      ),
    );

    await withLanguage("pl", async () => {
      render(<AppStore />, { wrapper: Wrapper });

      expect(
        await screen.findByText(
          new RegExp(tFor("common")("appStore.coreTeam")),
        ),
      ).toBeInTheDocument();
      expect(screen.queryByText(/Core Team/)).not.toBeInTheDocument();
    });
  });

  it("describes what a module needs in user terms, not as developer keywords", async () => {
    server.use(
      http.get("/api/v1/modules/available", () =>
        HttpResponse.json(
          onePage([
            pkg({
              capabilities: [
                "database",
                "filesystem",
                "process",
                "custom_thing",
              ],
            }),
          ]),
        ),
      ),
    );

    await withLanguage("pl", async () => {
      render(<AppStore />, { wrapper: Wrapper });

      const line = await screen.findByText(
        new RegExp(`^${tFor("common")("appStore.capabilities", { list: "" })}`),
      );
      expect(line).not.toHaveTextContent(/database|filesystem|process/);
      expect(line).toHaveTextContent(
        tFor("common")("appStore.capability_database"),
      );
      // A community module may declare a word the app does not know: shown as is.
      expect(line).toHaveTextContent("custom_thing");
    });
  });
});

describe("AppStore in focus mode", () => {
  it("hides enabled background providers from the catalogue", async () => {
    vi.spyOn(modulesCtx, "useModules").mockReturnValue({
      enabledModules: ["recipes", "shopping_lists"],
      hiddenModules: ["shopping_lists"],
      focusModule: "recipes",
      isModuleEnabled: () => true,
      isLoading: false,
      refreshModules: vi.fn(),
    });
    server.use(
      http.get("/api/v1/modules/available", () =>
        HttpResponse.json(
          onePage([
            {
              name: "recipes",
              display_name: "Recipes",
              description: "Recipe management",
              icon: "chef-hat",
              requires: [],
              version: "1.0.0",
            },
            {
              name: "shopping_lists",
              display_name: "Shopping Lists",
              description: "Background shopping",
              icon: "shopping-cart",
              requires: [],
              version: "1.0.0",
            },
          ]),
        ),
      ),
    );
    render(<AppStore />, { wrapper: Wrapper });
    expect(
      await screen.findByRole("heading", {
        name: tFor("modules")("modules.recipes.name"),
        level: 2,
      }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("heading", {
        name: tFor("modules")("modules.shopping_lists.name"),
        level: 2,
      }),
    ).not.toBeInTheDocument();
  });
});
