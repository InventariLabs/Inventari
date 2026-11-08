import { render, screen, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { BrowserRouter } from "react-router-dom";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ModulesProvider } from "@/contexts/ModulesContext";
import { withLanguage } from "@/test/mocks/i18n";
import { useFormGuardStore } from "@/store/formGuardStore";
import { CommandPalette } from "./CommandPalette";
import { Sheet, type SheetZTier } from "@/components/ui/Sheet";
// Side-effect: register the inventory module so the "Switch to" section
// has content to filter (registry is empty unless a module file imports it).
import "@/modules/inventory/module";
// Settings registers launcher.linkTo and routes: [] — the palette's module
// switch must land on the link, not fall through to "/".
import "@/modules/settings/module";
import "@/modules/shopping_lists/module";
import "@/modules/equipment/module";
const moduleVisibility = vi.hoisted(() => ({
  hidden: [] as string[],
  extraEnabled: [] as string[],
}));
vi.mock("@/contexts/ModulesContext", async (importOriginal) => {
  const actual =
    await importOriginal<typeof import("@/contexts/ModulesContext")>();
  return {
    ...actual,
    useModules: () => ({
      ...actual.useModules(),
      hiddenModules: moduleVisibility.hidden,
      enabledModules: [
        ...actual.useModules().enabledModules,
        ...moduleVisibility.extraEnabled,
      ],
    }),
  };
});
afterEach(() => {
  recent.items = [];
  moduleVisibility.hidden = [];
  moduleVisibility.extraEnabled = [];
});

if (typeof globalThis.ResizeObserver === "undefined") {
  globalThis.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver;
}

vi.mock("@/lib/useCommandPaletteSearch", () => ({
  useCommandPaletteSearch: (query: string, modules: string[]) =>
    mockSearch(String(query), modules),
}));

const recent = vi.hoisted(() => ({
  items: [] as {
    id: string;
    title: string;
    module: string;
    path: string;
    timestamp: number;
  }[],
}));

vi.mock("@/store/authStore", () => ({
  useAuthStore: () => ({ user: { id: 1 } }),
}));

vi.mock("@/lib/recentItems", () => ({
  getRecentItems: () => recent.items,
  RECENT_ITEMS_SCOPE: "default",
}));

const mockSearch = vi.hoisted(() => vi.fn());
const mockNavigate = vi.hoisted(() => vi.fn());
vi.mock("react-router-dom", async (importOriginal) => {
  const actual = await importOriginal<typeof import("react-router-dom")>();
  return { ...actual, useNavigate: () => mockNavigate };
});
const renderPalette = (open = true) =>
  render(
    <QueryClientProvider client={new QueryClient()}>
      <BrowserRouter>
        <ModulesProvider>
          <CommandPalette open={open} onClose={vi.fn()} />
        </ModulesProvider>
      </BrowserRouter>
    </QueryClientProvider>,
  );

describe("CommandPalette — autofocus", () => {
  beforeEach(() => {
    mockSearch.mockReturnValue({ results: [], isLoading: false });
    document.body.innerHTML = "";
    document.body.focus();
  });

  it("focuses the search input when opened", async () => {
    renderPalette(true);

    const input = (await screen.findAllByLabelText(/Search or jump to/i))[0];

    await waitFor(() => {
      expect(document.activeElement).toBe(input);
    });
  });
});

describe("CommandPalette — search relevance", () => {
  beforeEach(() => {
    mockSearch.mockReturnValue({ results: [], isLoading: false });
    document.body.innerHTML = "";
    document.body.focus();
  });

  it("shows API results for a matching query", async () => {
    mockSearch.mockReturnValue({
      results: [
        {
          id: "item-1",
          title: "Bread",
          subtitle: "Bakery",
          path: "/inventory/items/1",
          module: "inventory",
        },
      ],
      isLoading: false,
    });
    const user = userEvent.setup();
    renderPalette(true);

    const input = await screen.findAllByLabelText(/Search or jump to/i);
    await user.type(input[0], "bread");

    expect(await screen.findByText("Bread")).toBeInTheDocument();
  });

  it("does not show navigation groups for an unrelated query", async () => {
    const user = userEvent.setup();
    renderPalette(true);

    const input = await screen.findAllByLabelText(/Search or jump to/i);
    await user.type(input[0], "milk");

    expect(screen.queryByText("Switch to")).not.toBeInTheDocument();
    expect(screen.queryByText("Quick actions")).not.toBeInTheDocument();
  });

  it("shows the empty state only for queries without any matches", async () => {
    const user = userEvent.setup();
    renderPalette(true);

    const input = await screen.findAllByLabelText(/Search or jump to/i);
    await user.type(input[0], "zzz-no-match");

    expect(await screen.findByText("No results")).toBeInTheDocument();
    expect(screen.queryByText("Switch to")).not.toBeInTheDocument();
  });

  it("keeps navigation visible when query matches a module name", async () => {
    const user = userEvent.setup();
    renderPalette(true);

    const input = await screen.findAllByLabelText(/Search or jump to/i);
    await user.type(input[0], "inventory");

    expect(await screen.findByText("Switch to")).toBeInTheDocument();
  });
});

describe("CommandPalette — Enter opens what was typed", () => {
  const hit = {
    id: "item-tuna",
    title: "Tuna in Oil",
    path: "/inventory/items/tuna",
    module: "inventory",
  };

  beforeEach(() => {
    mockNavigate.mockClear();
    document.body.innerHTML = "";
    document.body.focus();
  });

  it("does not offer a module whose letters merely contain the word", async () => {
    moduleVisibility.extraEnabled = ["equipment"];
    mockSearch.mockReturnValue({ results: [], isLoading: false });
    const user = userEvent.setup();
    renderPalette(true);

    await user.type(await screen.findByRole("combobox"), "tuna");

    // t-u-n-a all occur, in order, in "equipment tracking".
    expect(screen.queryByText("Equipment Tracking")).not.toBeInTheDocument();
  });

  it("still offers a module the word starts", async () => {
    moduleVisibility.extraEnabled = ["equipment"];
    mockSearch.mockReturnValue({ results: [], isLoading: false });
    const user = userEvent.setup();
    renderPalette(true);

    await user.type(await screen.findByRole("combobox"), "track");

    expect(await screen.findByText("Equipment Tracking")).toBeInTheDocument();
  });

  it("opens the first hit when the hits arrive after the module entry", async () => {
    mockSearch.mockReturnValue({ results: [], isLoading: true });
    const user = userEvent.setup();
    const view = renderPalette(true);
    const input = await screen.findByRole("combobox");

    // "inv" starts a module's name, so a module entry is there to be
    // highlighted before the server has answered.
    await user.type(input, "inv");
    expect(await screen.findByText("Switch to")).toBeInTheDocument();

    mockSearch.mockReturnValue({ results: [hit], isLoading: false });
    view.rerender(
      <QueryClientProvider client={new QueryClient()}>
        <BrowserRouter>
          <ModulesProvider>
            <CommandPalette open onClose={vi.fn()} />
          </ModulesProvider>
        </BrowserRouter>
      </QueryClientProvider>,
    );
    expect(await screen.findByText("Tuna in Oil")).toBeInTheDocument();
    await user.keyboard("{Enter}");

    expect(mockNavigate).toHaveBeenCalledWith("/inventory/items/tuna");
  });
});

/**
 * A search hit was tagged with the module's technical name run through
 * `capitalize`: "Inventory" beside a launcher tile and a navigation entry
 * that both read "Inwentarz".
 */
describe("CommandPalette — the module a hit came from", () => {
  beforeEach(() => {
    mockSearch.mockReturnValue({
      results: [
        {
          id: "item-1",
          title: "Oliwa z oliwek",
          module: "inventory",
          path: "/inventory/items?open=item-1",
        },
      ],
      isLoading: false,
    });
    document.body.innerHTML = "";
  });

  it("names it the way the launcher names it", async () => {
    await withLanguage("pl", async () => {
      renderPalette();
      await userEvent.type(await screen.findByRole("combobox"), "oliwa");

      await waitFor(() =>
        expect(screen.getByText("Inwentarz")).toBeInTheDocument(),
      );
      expect(screen.queryByText("inventory")).toBeNull();
    });
  });
});

describe("CommandPalette — where a module switch lands", () => {
  beforeEach(() => {
    mockSearch.mockReturnValue({ results: [], isLoading: false });
    mockNavigate.mockClear();
    document.body.innerHTML = "";
    document.body.focus();
  });

  it("lands a module without routes on its launcher link, not on /", async () => {
    const user = userEvent.setup();
    renderPalette(true);

    const input = (await screen.findAllByLabelText(/Search or jump to/i))[0];
    await user.type(input, "settings");

    const options = await screen.findAllByRole("option");
    expect(options).toHaveLength(1);
    expect(options[0].textContent).toContain("Settings");

    await user.click(options[0]);

    expect(mockNavigate).toHaveBeenCalledWith("/settings");
  });
});

/**
 * The palette is one of the persistent exits a dirty form has to survive.
 * It used to be the quiet one: the module tabs asked, and a "Switch to"
 * chosen a few pixels away threw the work away without a word.
 */
describe("CommandPalette — jumping away asks a dirty form first", () => {
  beforeEach(() => {
    mockSearch.mockReturnValue({ results: [], isLoading: false });
    mockNavigate.mockClear();
    document.body.innerHTML = "";
    document.body.focus();
    useFormGuardStore.getState().setDirtyForm(null);
  });

  it("asks before a switch leaves a dirty form behind, then navigates on confirm", async () => {
    const user = userEvent.setup();
    useFormGuardStore.getState().setDirtyForm("The asset form");
    renderPalette(true);

    const input = (await screen.findAllByLabelText(/Search or jump to/i))[0];
    await user.type(input, "settings");

    const options = await screen.findAllByRole("option");
    await user.click(options[0]);

    expect(mockNavigate).not.toHaveBeenCalled();
    expect(screen.getByText("Unsaved changes")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Leave anyway" }));

    // The jump happens in the confirm promise's continuation, not in the click.
    await waitFor(() => expect(mockNavigate).toHaveBeenCalledWith("/settings"));
  });

  it("keeps the palette open when the reader declines", async () => {
    const user = userEvent.setup();
    useFormGuardStore.getState().setDirtyForm("The asset form");
    renderPalette(true);

    const input = (await screen.findAllByLabelText(/Search or jump to/i))[0];
    await user.type(input, "settings");

    await user.click((await screen.findAllByRole("option"))[0]);
    await user.click(screen.getByRole("button", { name: "Cancel" }));

    expect(mockNavigate).not.toHaveBeenCalled();
    expect(screen.queryByText("Unsaved changes")).not.toBeInTheDocument();
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });

  it("hands the focus back to the search input when the reader declines", async () => {
    const user = userEvent.setup();
    useFormGuardStore.getState().setDirtyForm("The asset form");
    renderPalette(true);

    const input = (await screen.findAllByLabelText(/Search or jump to/i))[0];
    await user.type(input, "settings");
    await user.click((await screen.findAllByRole("option"))[0]);
    await user.click(screen.getByRole("button", { name: "Cancel" }));

    await waitFor(() => expect(document.activeElement).toBe(input));
    await user.keyboard("x");
    expect(input).toHaveValue("settingsx");
  });
});

it("offers an enabled module normally but hides it from Switch to in focus", async () => {
  mockSearch.mockReturnValue({ results: [], isLoading: false });
  const visible = renderPalette();
  await userEvent.type(await screen.findByRole("combobox"), "shopping");
  expect(
    await screen.findByRole("option", { name: /Shopping Lists/ }),
  ).toBeInTheDocument();
  visible.unmount();
  moduleVisibility.hidden = ["shopping_lists"];
  renderPalette();
  await userEvent.type(await screen.findByRole("combobox"), "shopping");
  expect(
    screen.queryByRole("option", { name: /Shopping Lists/ }),
  ).not.toBeInTheDocument();
  expect(screen.queryByText("Switch to")).not.toBeInTheDocument();
});

describe("CommandPalette — focus mode keeps hidden modules out", () => {
  beforeEach(() => {
    useFormGuardStore.getState().setDirtyForm(null);
    mockSearch.mockReset();
    mockSearch.mockReturnValue({ results: [], isLoading: false });
  });

  it("offers no quick action of a hidden module", async () => {
    moduleVisibility.hidden = ["inventory"];
    renderPalette();
    await userEvent.type(await screen.findByRole("combobox"), "add");
    expect(
      screen.queryByRole("option", { name: "Add new item" }),
    ).not.toBeInTheDocument();
    await userEvent.clear(screen.getByRole("combobox"));
    await userEvent.type(screen.getByRole("combobox"), "scan");
    expect(
      screen.queryByRole("option", { name: "Scan barcode" }),
    ).not.toBeInTheDocument();
  });

  it("does not ask the search to look in a hidden module", async () => {
    moduleVisibility.hidden = ["inventory"];
    renderPalette();
    await userEvent.type(await screen.findByRole("combobox"), "flour");
    const modules = mockSearch.mock.calls.at(-1)?.[1] as string[];
    expect(modules).toContain("settings");
    expect(modules).not.toContain("inventory");
  });

  it("leaves a recently visited page of a hidden module out", async () => {
    recent.items = [
      {
        id: "i1",
        title: "Flour",
        module: "inventory",
        path: "/inventory/items/i1",
        timestamp: 1,
      },
    ];
    const visible = renderPalette();
    await userEvent.type(await screen.findByRole("combobox"), "flour");
    expect(
      await screen.findByRole("option", { name: /Flour/ }),
    ).toBeInTheDocument();
    visible.unmount();
    moduleVisibility.hidden = ["inventory"];
    renderPalette();
    await userEvent.type(await screen.findByRole("combobox"), "flour");
    expect(
      screen.queryByRole("option", { name: /Flour/ }),
    ).not.toBeInTheDocument();
  });
});

describe("CommandPalette — the scan screens", () => {
  beforeEach(() => {
    useFormGuardStore.getState().setDirtyForm(null);
    mockSearch.mockReturnValue({ results: [], isLoading: false });
    mockNavigate.mockClear();
  });

  it("offers the document scan screen where the warehouse module is on", async () => {
    moduleVisibility.extraEnabled = ["warehouse"];
    renderPalette();
    await userEvent.type(await screen.findByRole("combobox"), "scan");
    await userEvent.click(
      await screen.findByRole("option", { name: "Scan document" }),
    );
    await waitFor(() =>
      expect(mockNavigate).toHaveBeenCalledWith("/warehouse/scan"),
    );
  });

  it("leaves it out where the warehouse module is off", async () => {
    renderPalette();
    await userEvent.type(await screen.findByRole("combobox"), "scan");
    expect(
      await screen.findByRole("option", { name: "Scan barcode" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("option", { name: "Scan document" }),
    ).not.toBeInTheDocument();
  });
});

describe("CommandPalette — it opens over whatever sheet is open", () => {
  beforeEach(() => {
    mockSearch.mockReturnValue({ results: [], isLoading: false });
    mockNavigate.mockClear();
    document.body.innerHTML = "";
    document.body.focus();
    useFormGuardStore.getState().setDirtyForm(null);
  });

  // The palette opens from anywhere with Ctrl+K, so the sheet under it can
  // stand on any tier. Opened under one it was invisible and pointer-dead,
  // yet Enter still navigated the route behind the form.
  const renderOverSheet = (
    tier: SheetZTier,
    onSheetClose = vi.fn(),
    onPaletteClose = vi.fn(),
  ) => {
    const tree = (paletteOpen: boolean) => (
      <QueryClientProvider client={new QueryClient()}>
        <BrowserRouter>
          <ModulesProvider>
            <Sheet open onClose={onSheetClose} zIndex={tier}>
              <p>The form underneath</p>
            </Sheet>
            <CommandPalette open={paletteOpen} onClose={onPaletteClose} />
          </ModulesProvider>
        </BrowserRouter>
      </QueryClientProvider>
    );
    // The sheet is on screen first; the palette is opened over it.
    const view = render(tree(false));
    view.rerender(tree(true));
    return view;
  };

  const tierOf = (node: HTMLElement) =>
    /z-\[var\((--z-[a-z-]+)\)\]/.exec(node.className)?.[1];

  it.each<SheetZTier>(["modal", "modal-nested", "confirm", "fullscreen"])(
    "stands above a %s sheet",
    async (tier) => {
      renderOverSheet(tier);

      const palette = await screen.findByRole("dialog", {
        name: "Command palette",
      });
      const sheetText = screen.getByText("The form underneath");

      // The highest sheet tier, and later in the document than the sheet:
      // at an equal tier the later layer paints on top.
      expect(tierOf(palette)).toBe("--z-fullscreen");
      expect(
        sheetText.compareDocumentPosition(palette) &
          Node.DOCUMENT_POSITION_FOLLOWING,
      ).toBeTruthy();
    },
  );

  it("closes itself on Escape and leaves the sheet under it open", async () => {
    const onSheetClose = vi.fn();
    const onPaletteClose = vi.fn();
    const user = userEvent.setup();
    renderOverSheet("confirm", onSheetClose, onPaletteClose);

    await screen.findByRole("dialog", { name: "Command palette" });
    await user.keyboard("{Escape}");

    expect(onPaletteClose).toHaveBeenCalled();
    expect(onSheetClose).not.toHaveBeenCalled();
  });

  it("asks about a dirty form above itself, not under it", async () => {
    const user = userEvent.setup();
    useFormGuardStore.getState().setDirtyForm("The asset form");
    renderOverSheet("confirm");

    await user.type(await screen.findByRole("combobox"), "settings");
    await user.click((await screen.findAllByRole("option"))[0]);

    const question = screen.getByRole("alertdialog");
    expect(question.style.zIndex).toBe("var(--z-fullscreen)");
  });
});
