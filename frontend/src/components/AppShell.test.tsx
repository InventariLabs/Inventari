import { readFileSync } from "node:fs";
import { join } from "node:path";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import {
  Link,
  MemoryRouter,
  Route,
  Routes,
  useLocation,
} from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import AppShell from "./AppShell";
import "@/modules/warehouse/module";
import { useFormGuardStore } from "@/store/formGuardStore";
import { http, HttpResponse } from "msw";
import { server } from "@/test/mocks/server";

/**
 * The header is one of the persistent exits a dirty form has to survive.
 * It used to be the hole in the gate: the module tabs asked, the module
 * switcher asked, and clicking the very same address on the logo or the
 * settings link threw the work away without a word.
 */

/** The module set the shell resolves against. A test that needs the module
 *  header turns one on for its own render and the reset below puts it back. */
const modulesState: {
  enabledModules: string[];
  focusModule: string | null;
  focusStatus: "loading" | "failed" | "ready";
} = {
  enabledModules: [],
  focusModule: null,
  focusStatus: "ready",
};

vi.mock("@/contexts/ModulesContext", () => ({
  useModules: () => ({
    enabledModules: modulesState.enabledModules,
    hiddenModules: [],
    focusModule: modulesState.focusModule,
    focusStatus: modulesState.focusStatus,
    isModuleEnabled: (name: string) =>
      modulesState.enabledModules.includes(name),
    isLoading: false,
    refreshModules: vi.fn(),
  }),
}));

const authState = { role: "user" };

vi.mock("@/store/authStore", () => ({
  useAuthStore: (select?: (state: unknown) => unknown) => {
    const state = {
      user: {
        id: "user-1",
        email: "reader@example.com",
        full_name: "Reader",
        role: authState.role,
        organization_id: "org-1",
        is_superuser: false,
      },
      logout: vi.fn(),
    };
    return select ? select(state) : state;
  },
}));

vi.mock("@/hooks/useActiveProfile", () => ({
  useActiveProfile: () => ({
    id: "food_home",
    branding: { subtitle_key: "profiles.food_home.subtitle" },
  }),
}));

// jsdom has no scrolling; the shell resets the position on a new screen.
beforeEach(() => {
  window.scrollTo = vi.fn();
});

function LocationProbe() {
  const location = useLocation();
  return <div data-testid="path">{location.pathname}</div>;
}

function renderShell(initialPath = "/equipment", state?: unknown) {
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter initialEntries={[{ pathname: initialPath, state }]}>
        <Routes>
          <Route path="*" element={<AppShell />}>
            <Route path="*" element={<LocationProbe />} />
          </Route>
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("AppShell — the header's exits walk the same gate as the module tabs", () => {
  beforeEach(() => {
    useFormGuardStore.getState().setDirtyForm(null);
    modulesState.enabledModules = [];
    modulesState.focusModule = null;
  });

  it("navigates without asking when nothing is dirty", async () => {
    const user = userEvent.setup();
    renderShell();

    await user.click(screen.getByLabelText("Settings"));

    expect(screen.getByTestId("path")).toHaveTextContent("/settings");
    expect(screen.queryByText("Unsaved changes")).not.toBeInTheDocument();
  });

  it("asks before the settings link leaves a dirty form behind", async () => {
    const user = userEvent.setup();
    useFormGuardStore.getState().setDirtyForm("The asset form");
    renderShell();

    await user.click(screen.getByLabelText("Settings"));

    expect(screen.getByTestId("path")).toHaveTextContent("/equipment");
    expect(screen.getByText("Unsaved changes")).toBeInTheDocument();
    expect(
      screen.getByText("The asset form holds unsaved changes. Leave anyway?"),
    ).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Leave anyway" }));

    // The navigation lands a tick after the click resolves; reading the
    // path immediately races the router and loses under load.
    await waitFor(() =>
      expect(screen.getByTestId("path")).toHaveTextContent("/settings"),
    );
  });

  it("gives the same answer for the same address whichever control carries it", async () => {
    const user = userEvent.setup();
    useFormGuardStore.getState().setDirtyForm("The asset form");
    renderShell();

    // The logo goes to /launcher, the settings link to /settings — both are
    // exits, and neither may be the quiet one.
    await user.click(screen.getByRole("link", { name: /^Inventari/ }));
    expect(screen.getByText("Unsaved changes")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Cancel" }));

    await user.click(screen.getByLabelText("Settings"));
    expect(screen.getByText("Unsaved changes")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Cancel" }));

    expect(screen.getByTestId("path")).toHaveTextContent("/equipment");
  });
});

/**
 * A control whose `aria-label` leaves out the words it shows cannot be called
 * by those words: a voice user says "click Search or jump to" and nothing
 * answers, because the button is named "Command palette" (WCAG 2.5.3, axe
 * `label-content-name-mismatch`). The words on screen are part of the name.
 */
describe("AppShell — header controls are named by the words they show", () => {
  beforeEach(() => {
    modulesState.enabledModules = [];
    modulesState.focusModule = null;
  });

  /** The text a sighted reader sees: hidden and screen-reader-only parts out. */
  const shownText = (el: Element): string =>
    Array.from(el.childNodes)
      .map((node) => {
        if (node.nodeType === Node.TEXT_NODE) return node.textContent ?? "";
        if (!(node instanceof Element)) return "";
        if (node.getAttribute("aria-hidden") === "true") return "";
        if (node.classList.contains("sr-only")) return "";
        return ` ${shownText(node)} `;
      })
      .join("")
      .replace(/\s+/g, " ")
      .trim();

  it.each(["/settings", "/equipment/assets"])(
    "keeps every label on %s a superset of what it shows",
    (path) => {
      modulesState.enabledModules = ["equipment"];
      renderShell(path);

      const header = document.querySelector("header")!;
      const labelled = header.querySelectorAll("[aria-label]");
      expect(labelled.length).toBeGreaterThan(0);
      for (const el of labelled) {
        const shown = shownText(el).toLowerCase();
        if (!shown) continue;
        expect(el.getAttribute("aria-label")!.toLowerCase()).toContain(shown);
      }
    },
  );

  it("sends the phone Back to the screen that linked here, else to the module's root", async () => {
    const user = userEvent.setup();
    useFormGuardStore.getState().setDirtyForm(null);
    modulesState.enabledModules = ["equipment"];
    const { unmount } = renderShell("/equipment/assets", {
      backTo: "/warehouse/todo",
    });
    await user.click(screen.getByRole("button", { name: "Back" }));
    await waitFor(() =>
      expect(screen.getByTestId("path")).toHaveTextContent("/warehouse/todo"),
    );
    unmount();

    // Entered by a direct link there is nothing to go back to: the parent.
    renderShell("/equipment/assets/a1");
    await user.click(screen.getByRole("button", { name: "Back" }));
    await waitFor(() =>
      expect(screen.getByTestId("path")).toHaveTextContent(
        /^\/equipment\/assets$/,
      ),
    );
  });

  it("leaves the module only from its root", async () => {
    const user = userEvent.setup();
    modulesState.enabledModules = ["equipment"];
    renderShell("/equipment");
    await user.click(screen.getByRole("button", { name: "Back" }));
    await waitFor(() =>
      expect(screen.getByTestId("path")).toHaveTextContent("/launcher"),
    );
  });

  it("sends the phone Back to the previous screen, not out of the module", async () => {
    const user = userEvent.setup();
    modulesState.enabledModules = ["equipment"];
    render(
      <QueryClientProvider client={new QueryClient()}>
        <MemoryRouter
          initialEntries={["/equipment/assets", "/equipment/assets/a1"]}
          initialIndex={1}
        >
          <Routes>
            <Route path="*" element={<AppShell />}>
              <Route path="*" element={<LocationProbe />} />
            </Route>
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );
    await user.click(screen.getByRole("button", { name: "Back" }));
    await waitFor(() =>
      expect(screen.getByTestId("path")).toHaveTextContent(
        /^\/equipment\/assets$/,
      ),
    );
  });

  it("climbs to the parent when a replaced screen has no earlier entry", async () => {
    // A `replace` gives the screen a fresh key without adding history, so the
    // key alone says "there is something behind" where there is nothing: the
    // browser's own entry count (idx 0) is the truth. Back used to do nothing.
    window.history.replaceState({ idx: 0, key: "fresh" }, "");
    const user = userEvent.setup();
    modulesState.enabledModules = ["equipment"];
    render(
      <QueryClientProvider client={new QueryClient()}>
        <MemoryRouter
          initialEntries={["/equipment", "/equipment/assets/a1"]}
          initialIndex={1}
        >
          <Routes>
            <Route path="*" element={<AppShell />}>
              <Route path="*" element={<LocationProbe />} />
            </Route>
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );
    await user.click(screen.getByRole("button", { name: "Back" }));
    window.history.replaceState(null, "");
    await waitFor(() =>
      expect(screen.getByTestId("path")).toHaveTextContent(
        /^\/equipment\/assets$/,
      ),
    );
  });

  it("names the home link by the wordmark it shows", () => {
    renderShell();

    expect(
      screen.getByRole("link", { name: "Inventari for Home" }),
    ).toHaveAttribute("href", "/launcher");
  });

  it("names the search button by its placeholder, not by the feature", () => {
    renderShell();

    const search = screen.getAllByRole("button", {
      name: "Search or jump to…",
    });
    // The wide button and the icon-only one below `sm:` open the same palette
    // and carry the same name.
    expect(search).toHaveLength(2);
    expect(search[0]).toHaveAttribute("aria-keyshortcuts", "Control+K Meta+K");
  });
});

/**
 * At 390px the wordmark link measured 151x24 wherever the header
 * shows it: the wordmark's own line box, with nothing around it to tap. The
 * hit area grows; the glyphs do not. jsdom has no layout, so these pin the
 * classes; the measurement comes from a real 390px screen.
 */
describe("AppShell — the wordmark link is a 44px target", () => {
  beforeEach(() => {
    modulesState.enabledModules = [];
  });

  it("pads the home link instead of growing the wordmark", () => {
    renderShell();

    const home = screen.getByRole("link", { name: /^Inventari/ });
    // 24px of line box between 10px of padding top and bottom = the 44px floor
    // below `md`, where a thumb asks. Above it the header stays as dense.
    expect(home.className).toContain("py-2.5");
    expect(home.querySelector("span")?.className).toContain("text-base");
  });

  it("carries it in the module header, where the logo shares the row", () => {
    modulesState.enabledModules = ["equipment"];
    renderShell("/equipment/assets");

    // Both header layouts wrap the same wordmark in the same link — one is
    // hidden below `md`, the other on every module route — so a hit area
    // added to one and not the other is half the app.
    expect(
      screen.getByRole("link", { name: /^Inventari/ }).className,
    ).toContain("py-2.5");
  });
});

/**
 * `overflow-x-hidden` on the root made it a scroll container that never
 * scrolls, so every `sticky` element below it — the module nav, the footer of
 * a full-page form — stuck to that box and scrolled away with the page. jsdom
 * has no layout, so this pins the class; the measurement is a real screen
 * scrolled past the first fold.
 */
describe("AppShell — the root clips the side without becoming a scroll container", () => {
  it("clips with overflow-x-clip, which leaves sticky children pinned to the window", () => {
    modulesState.enabledModules = [];
    const { container } = renderShell();

    const root = container.querySelector("div.min-h-screen");
    expect(root?.className).toContain("overflow-x-clip");
    expect(root?.className).not.toContain("overflow-x-hidden");
  });
});

/**
 * The strip under the top bar (the demo notice and whatever a module puts in
 * `global_notifications`) paints in the layer system, below the bar.
 *
 * It sat on the bar's own tier and later in the document, so it painted over
 * everything the bar opens: the first entries of the theme, language and
 * account menus ended up underneath it, visible in the tree and impossible to
 * click.
 */
describe("AppShell — the notification strip stays under the top bar", () => {
  const INDEX_CSS = readFileSync(join(__dirname, "..", "index.css"), "utf8");
  const tier = (token: string) =>
    Number(new RegExp(`${token}:\\s*(\\d+)`).exec(INDEX_CSS)?.[1]);
  const tierOf = (el: Element) => {
    const token = /z-\[var\((--z-[\w-]+)\)\]/.exec(el.className)?.[1];
    return token ? tier(token) : NaN;
  };

  it("takes a tier from the layer system that is lower than the bar's", () => {
    const { container } = renderShell();

    const bar = container.querySelector("header");
    const strip = container.querySelector("main > div.sticky");
    expect(bar).not.toBeNull();
    expect(strip).not.toBeNull();
    // A hard-coded value (z-50) has no token and reads as NaN here.
    expect(tierOf(strip!)).toBeLessThan(tierOf(bar!));
    expect(tierOf(strip!)).toBeGreaterThan(tier("--z-sticky") - 1);
  });
});

describe("AppShell — the sticky bars below the strip stack under it", () => {
  const observers: Array<() => void> = [];
  const realObserver = globalThis.ResizeObserver;

  beforeEach(() => {
    observers.length = 0;
    globalThis.ResizeObserver = class {
      constructor(callback: () => void) {
        observers.push(callback);
      }
      observe() {}
      unobserve() {}
      disconnect() {}
    } as unknown as typeof ResizeObserver;
  });

  afterEach(() => {
    globalThis.ResizeObserver = realObserver;
  });

  const wideScreen = (matches: boolean) =>
    vi.spyOn(window, "matchMedia").mockImplementation(
      (query) =>
        ({
          matches,
          media: query,
          addEventListener: vi.fn(),
          removeEventListener: vi.fn(),
        }) as unknown as MediaQueryList,
    );

  it("publishes nothing for a strip that scrolls away on a phone", () => {
    wideScreen(false);
    vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockImplementation(
      function (this: HTMLElement) {
        return {
          height: this.matches("main > div.sticky") ? 40 : 0,
        } as DOMRect;
      },
    );
    renderShell();
    expect(
      document.documentElement.style.getPropertyValue("--app-notice-height"),
    ).toBe("0px");
    vi.restoreAllMocks();
  });

  it("publishes the strip's height, and follows it when it changes", () => {
    wideScreen(true);
    let height = 0;
    vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockImplementation(
      function (this: HTMLElement) {
        const strip = this.matches("main > div.sticky");
        return { height: strip ? height : 0 } as DOMRect;
      },
    );
    renderShell();
    // On the root element, where the page's scroll padding reads it too.
    const root = document.documentElement;

    // No notice: the module nav sticks right under the bar.
    expect(root.style.getPropertyValue("--app-notice-height")).toBe("0px");

    // The demo notice arrives.
    height = 40;
    observers.forEach((notify) => notify());
    expect(root.style.getPropertyValue("--app-notice-height")).toBe("40px");
    vi.restoreAllMocks();
  });
});

describe("AppShell — work mode narrows the header's identity", () => {
  beforeEach(() => {
    modulesState.enabledModules = [];
    modulesState.focusModule = null;
    modulesState.focusStatus = "ready";
  });

  it("claims no profile while the focus state is unknown", () => {
    for (const status of ["loading", "failed"] as const) {
      modulesState.focusStatus = status;
      const { unmount } = renderShell();
      expect(screen.queryByText("for Home")).not.toBeInTheDocument();
      unmount();
    }
  });

  it("shows the profile label outside work mode", () => {
    renderShell();
    expect(screen.getByText("for Home")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /^Inventari/ })).toHaveAttribute(
      "href",
      "/launcher",
    );
  });

  it("drops the profile label and the launcher link in work mode", () => {
    modulesState.focusModule = "equipment";
    renderShell();
    expect(screen.queryByText("for Home")).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: /^Inventari/ })).toHaveAttribute(
      "href",
      "/",
    );
  });
});

describe("AppShell — the header says the workspace shows one module", () => {
  beforeEach(() => {
    modulesState.enabledModules = [];
    modulesState.focusModule = "equipment";
    modulesState.focusStatus = "ready";
    authState.role = "user";
  });

  it("shows a member a label without an action", () => {
    renderShell();
    const note = screen.getByText(/^Set by an admin$/);
    expect(note.closest("a")).toBeNull();
    // The module name is its own visible text, so a narrow header cannot
    // truncate it away behind the sentence.
    expect(note.previousElementSibling).toHaveTextContent(/\S/);
  });

  it("leads an admin to Settings -> My modules", () => {
    authState.role = "admin";
    renderShell();
    const link = screen.getByRole("link", { name: /^You see only/ });
    expect(link).toHaveAttribute("href", "/settings/my-modules");
  });

  it("is absent when every module is showing and while the focus state is unknown", () => {
    modulesState.focusModule = null;
    const { unmount } = renderShell();
    expect(
      screen.queryByRole("link", { name: /^You see only/ }),
    ).not.toBeInTheDocument();
    unmount();

    modulesState.focusModule = "equipment";
    for (const status of ["loading", "failed"] as const) {
      modulesState.focusStatus = status;
      const { unmount: again } = renderShell();
      expect(
        screen.queryByRole("link", { name: /^You see only/ }),
      ).not.toBeInTheDocument();
      again();
    }
  });
});

/**
 * The phone keeps the three working tabs in its bottom bar and puts the rest
 * one entry away. It used to mirror the desktop bar exactly, which is how
 * configuration screens reached the phone and the board would have.
 */
describe("AppShell — the phone's bar is the module's three working tabs", () => {
  beforeEach(() => {
    modulesState.focusModule = null;
    modulesState.focusStatus = "ready";
  });

  function bar() {
    return screen.getByRole("navigation", { name: "Module navigation" });
  }

  async function openMore() {
    await userEvent.click(within(bar()).getByRole("button", { name: "More" }));
  }

  it("shows Start, Scan document and History in the bar and Configuration under More", async () => {
    modulesState.enabledModules = ["warehouse"];
    renderShell("/warehouse/todo");
    const labels = within(bar())
      .getAllByRole("link")
      .map((link) => link.textContent);
    expect(labels).toEqual(["Start", "Scan document", "History"]);
    await openMore();
    expect(within(bar()).getByText("Configuration")).toBeInTheDocument();
    // Desk views are not phone tabs.
    expect(within(bar()).queryByText("Board")).not.toBeInTheDocument();
    expect(within(bar()).queryByText("Register")).not.toBeInTheDocument();
  });

  it("puts the approvals count on Start, not a tab of its own", async () => {
    modulesState.enabledModules = ["warehouse", "approvals"];
    server.use(
      http.get("/api/v1/warehouse/awaiting-my-approval", () =>
        HttpResponse.json({ items: [], total: 2 }),
      ),
    );
    renderShell("/warehouse/todo");
    const start = within(bar()).getByRole("link", { name: /Start/ });
    await waitFor(() =>
      expect(within(start).getByText("2")).toBeInTheDocument(),
    );
    await openMore();
    expect(within(bar()).queryByText("Approvals")).not.toBeInTheDocument();
  });
});

describe("AppShell — a new screen opens at its top", () => {
  beforeEach(() => {
    modulesState.enabledModules = ["equipment"];
    modulesState.focusModule = null;
  });

  function renderWithLinks(initial = "/equipment/assets") {
    return render(
      <QueryClientProvider client={new QueryClient()}>
        <MemoryRouter initialEntries={[initial]}>
          <Routes>
            <Route path="*" element={<AppShell />}>
              <Route
                path="*"
                element={
                  <>
                    <LocationProbe />
                    <Link to="/equipment/assets/a1">detail</Link>
                    <Link to="/equipment/assets?q=x">filter</Link>
                  </>
                }
              />
            </Route>
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );
  }

  it("scrolls to the top when a link changes the screen", async () => {
    const scrollTo = vi.mocked(window.scrollTo);
    const user = userEvent.setup();
    renderWithLinks();
    scrollTo.mockClear();

    await user.click(screen.getByRole("link", { name: "detail" }));

    await waitFor(() => expect(scrollTo).toHaveBeenCalledWith(0, 0));
  });

  it("leaves the position alone when only the query string changes", async () => {
    const scrollTo = vi.mocked(window.scrollTo);
    const user = userEvent.setup();
    renderWithLinks();
    scrollTo.mockClear();

    await user.click(screen.getByRole("link", { name: "filter" }));

    expect(screen.getByTestId("path")).toHaveTextContent("/equipment/assets");
    expect(scrollTo).not.toHaveBeenCalled();
  });
});
