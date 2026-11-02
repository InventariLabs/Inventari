import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, it, expect, vi } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import { server } from "@/test/mocks/server";
import { FocusDiffPreview, FocusModeSettings } from "./FocusModeSettings";
import type { ModuleInfo } from "@/types";
import type { FocusModeResponse } from "@/lib/api/modules";
import { onePage } from "@/test/mocks/page";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn(), loading: vi.fn() },
}));

const enabledModules = [
  "core",
  "items",
  "locations",
  "equipment",
  "shopping_lists",
  "nutrition",
];

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
    name: "equipment",
    display_name: "Equipment Tracking",
    description: "Track IT assets.",
    icon: "laptop",
    category: "business",
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
    name: "items",
    display_name: "Items",
    description: "Inventory items.",
    icon: "box",
    category: "core",
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
    name: "shopping_lists",
    display_name: "Shopping Lists",
    description: "Shopping lists.",
    icon: "list",
    category: "business",
    requires: ["items"],
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
    name: "nutrition",
    display_name: "Nutrition",
    description: "Nutrition data.",
    icon: "apple",
    category: "analytics",
    requires: [],
    version: "1.0.0",
  },
];

const previewResponse: FocusModeResponse = {
  applied: false,
  focus_module: null,
  diff: {
    focus_module: "equipment",
    enable: [],
    disable: ["items"],
    cascade_disable: ["nutrition"],
    disable_all: ["nutrition", "items"],
    unchanged: ["core", "shopping_lists"],
    manual_kept: [],
    final_enabled_modules: ["core", "equipment", "shopping_lists"],
    warnings: ["nutrition was disabled because it requires items"],
  },
};

const applyResponse: FocusModeResponse = {
  applied: true,
  focus_module: "equipment",
  enabled_modules: ["core", "equipment", "shopping_lists"],
  diff: null,
};

const focusedResponse: FocusModeResponse = {
  applied: true,
  focus_module: "equipment",
  enabled_modules: ["core", "equipment", "shopping_lists"],
  diff: null,
};

function renderFocus() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <FocusModeSettings />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function mockBaseEndpoints(modules: string[] = enabledModules) {
  server.use(
    http.get("*/api/v1/modules/my", () => HttpResponse.json(modules)),
    http.get("*/api/v1/modules/available", () =>
      HttpResponse.json(onePage(moduleCatalog)),
    ),
  );
}

async function toggleEquipment() {
  const toggle = await screen.findByRole("checkbox", {
    name: "Show only Equipment Tracking",
  });
  await userEvent.click(toggle);
}

describe("FocusModeSettings", () => {
  it("offers every module that can stand alone as a 'Show only <name>' toggle", async () => {
    mockBaseEndpoints();
    renderFocus();

    expect(
      await screen.findByRole("checkbox", {
        name: "Show only Equipment Tracking",
      }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("checkbox", { name: "Show only Shopping Lists" }),
    ).toBeInTheDocument();
    // Only what declared `standalone` in its manifest is offered.
    expect(
      screen.queryByRole("checkbox", { name: /Nutrition/ }),
    ).not.toBeInTheDocument();
  });

  it("asks what will change before showing one module, and confirms with POST /modules/focus", async () => {
    const calls: Array<Record<string, unknown>> = [];
    let captured: Record<string, unknown> | null = null;
    mockBaseEndpoints();
    server.use(
      http.post("*/api/v1/modules/focus/preview", async ({ request }) => {
        captured = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json(previewResponse);
      }),
      http.post("*/api/v1/modules/focus", async ({ request }) => {
        calls.push((await request.json()) as Record<string, unknown>);
        return HttpResponse.json(applyResponse);
      }),
    );
    renderFocus();
    await toggleEquipment();
    await waitFor(() => {
      expect(captured).toEqual({ module_name: "equipment" });
    });

    // The question carries the whole change: what switches off (chips plus
    // the backend's cascade reason verbatim), what hides from navigation,
    // and no renamed core labels — equipment declares no i18nOverrides, so
    // a renamed tab that does not carry the page under it would give one
    // concept two names.
    const dialog = await screen.findByRole("alertdialog");
    expect(dialog).toHaveTextContent("Show only Equipment Tracking?");
    expect(dialog).toHaveTextContent("Will switch off");
    // The visible name comes from modules.items.name (the inventory card),
    // not from the manifest fallback — a missing key used to let the raw
    // "Items" through here.
    expect(dialog).toHaveTextContent("Inventory");
    expect(dialog).toHaveTextContent("Nutrition");
    expect(dialog).toHaveTextContent(
      "nutrition was disabled because it requires items",
    );
    expect(dialog).toHaveTextContent("Will hide from navigation");
    expect(dialog).toHaveTextContent("Shopping Lists");
    expect(dialog).not.toHaveTextContent("Will be renamed");

    await userEvent.click(
      within(dialog).getByRole("button", { name: /show only this module/i }),
    );
    await waitFor(() => {
      expect(calls).toContainEqual({ module_name: "equipment" });
    });
  });

  it("leaves the toggle off when the question is cancelled", async () => {
    const posts: unknown[] = [];
    mockBaseEndpoints();
    server.use(
      http.post("*/api/v1/modules/focus/preview", () =>
        HttpResponse.json(previewResponse),
      ),
      http.post("*/api/v1/modules/focus", async () => {
        posts.push(1);
        return HttpResponse.json(applyResponse);
      }),
    );
    renderFocus();
    await toggleEquipment();

    const dialog = await screen.findByRole("alertdialog");
    await userEvent.click(
      within(dialog).getByRole("button", { name: /cancel/i }),
    );

    await waitFor(() =>
      expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument(),
    );
    expect(
      screen.getByRole("checkbox", { name: "Show only Equipment Tracking" }),
    ).not.toBeChecked();
    expect(posts).toEqual([]);
  });

  it("says the preview failed and offers a retry", async () => {
    mockBaseEndpoints();
    server.use(
      http.post("*/api/v1/modules/focus/preview", () =>
        HttpResponse.json({ detail: "boom" }, { status: 500 }),
      ),
    );
    renderFocus();
    await toggleEquipment();

    const note = await screen.findByTestId("focus-preview-failed");
    expect(note).toHaveTextContent(
      /preview of this change could not be loaded/,
    );
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
  });

  it("puts the toggle back when the preview fails — the choice was never saved", async () => {
    let deletes = 0;
    mockBaseEndpoints();
    server.use(
      http.post("*/api/v1/modules/focus/preview", () =>
        HttpResponse.json({ detail: "boom" }, { status: 500 }),
      ),
      http.delete("*/api/v1/modules/focus", () => {
        deletes += 1;
        return HttpResponse.json({ applied: false, focus_module: null });
      }),
    );
    renderFocus();
    await toggleEquipment();

    await screen.findByTestId("focus-preview-failed");
    // The server has no focus, so nothing may read as on. And the box the
    // failed choice left behind must never become "undo = show all": that
    // DELETE has nothing to leave and answers 409.
    expect(
      screen.getByRole("checkbox", { name: "Show only Equipment Tracking" }),
    ).not.toBeChecked();
    await userEvent.click(
      screen.getByRole("checkbox", { name: "Show only Equipment Tracking" }),
    );
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
    expect(deletes).toBe(0);
  });

  it("keeps the module the organization is in when a preview of a replacement fails", async () => {
    let deletes = 0;
    mockBaseEndpoints();
    server.use(
      http.get("*/api/v1/modules/focus", () =>
        HttpResponse.json(focusedResponse),
      ),
      http.post("*/api/v1/modules/focus/preview", () =>
        HttpResponse.json({ detail: "boom" }, { status: 500 }),
      ),
      http.delete("*/api/v1/modules/focus", () => {
        deletes += 1;
        return HttpResponse.json({ applied: false, focus_module: null });
      }),
    );
    renderFocus();

    await userEvent.click(
      await screen.findByRole("checkbox", {
        name: "Show only Shopping Lists",
      }),
    );
    await screen.findByTestId("focus-preview-failed");

    // The replacement was never saved: the module being displayed stays on
    // and the candidate stays off. The failed attempt must not walk into the
    // saved-focus exit either — that would delete the focus it failed to
    // replace.
    expect(
      screen.getByRole("checkbox", { name: "Show only Shopping Lists" }),
    ).not.toBeChecked();
    expect(
      screen.getByRole("checkbox", { name: "Show only Equipment Tracking" }),
    ).toBeChecked();
    expect(deletes).toBe(0);
  });

  it("asks again when the reader retries a preview that failed", async () => {
    let previews = 0;
    mockBaseEndpoints();
    server.use(
      http.post("*/api/v1/modules/focus/preview", () => {
        previews += 1;
        return previews === 1
          ? HttpResponse.json({ detail: "boom" }, { status: 500 })
          : HttpResponse.json(previewResponse);
      }),
      http.post("*/api/v1/modules/focus", () =>
        HttpResponse.json(applyResponse),
      ),
    );
    renderFocus();
    await toggleEquipment();
    await screen.findByTestId("focus-preview-failed");

    // The failed choice is remembered by the retry button, not by the toggle.
    await userEvent.click(screen.getByRole("button", { name: /try again/i }));

    const dialog = await screen.findByRole("alertdialog");
    expect(dialog).toHaveTextContent("Show only Equipment Tracking?");
    expect(previews).toBe(2);
  });

  it("keeps the question standing with the reason when writing a replacement fails", async () => {
    let deletes = 0;
    mockBaseEndpoints();
    server.use(
      http.get("*/api/v1/modules/focus", () =>
        HttpResponse.json(focusedResponse),
      ),
      http.post("*/api/v1/modules/focus/preview", () =>
        HttpResponse.json(previewResponse),
      ),
      http.post("*/api/v1/modules/focus", () =>
        HttpResponse.json({ detail: "boom" }, { status: 409 }),
      ),
      http.delete("*/api/v1/modules/focus", () => {
        deletes += 1;
        return HttpResponse.json({ applied: false, focus_module: null });
      }),
    );
    renderFocus();
    await userEvent.click(
      await screen.findByRole("checkbox", {
        name: "Show only Shopping Lists",
      }),
    );
    const dialog = await screen.findByRole("alertdialog");
    await userEvent.click(
      within(dialog).getByRole("button", { name: /show only this module/i }),
    );

    // The write was refused, so the question stands with the reason instead
    // of closing like a success; the focus it would have replaced is only
    // left when the reader says so.
    await waitFor(() => {
      expect(within(dialog).getByRole("alert")).toBeInTheDocument();
    });
    await userEvent.click(
      within(dialog).getByRole("button", { name: /cancel/i }),
    );
    await waitFor(() =>
      expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument(),
    );
    expect(
      screen.getByRole("checkbox", { name: "Show only Shopping Lists" }),
    ).not.toBeChecked();
    expect(
      screen.getByRole("checkbox", { name: "Show only Equipment Tracking" }),
    ).toBeChecked();
    expect(deletes).toBe(0);
  });

  it("keeps the module labels when the catalogue read fails", async () => {
    server.use(
      http.get("*/api/v1/modules/my", () => HttpResponse.json(enabledModules)),
      http.get("*/api/v1/modules/available", () =>
        HttpResponse.json({ detail: "boom" }, { status: 500 }),
      ),
    );
    renderFocus();

    expect(
      await screen.findByRole("checkbox", {
        name: "Show only Equipment Tracking",
      }),
    ).toBeInTheDocument();
  });

  it("shows the module being displayed as on and asks before showing all again", async () => {
    let deletes = 0;
    mockBaseEndpoints();
    server.use(
      http.get("*/api/v1/modules/focus", () =>
        HttpResponse.json(focusedResponse),
      ),
      http.delete("*/api/v1/modules/focus", () => {
        deletes += 1;
        return HttpResponse.json({ applied: false, focus_module: null });
      }),
    );
    renderFocus();

    const toggle = await screen.findByRole("checkbox", {
      name: "Show only Equipment Tracking",
    });
    expect(toggle).toBeChecked();

    await userEvent.click(toggle);
    const dialog = await screen.findByRole("alertdialog");
    expect(dialog).toHaveTextContent("Show all modules?");
    await userEvent.click(
      within(dialog).getByRole("button", { name: /show all modules/i }),
    );
    await waitFor(() => expect(deletes).toBe(1));
  });

  it("renders an explanatory empty state when nothing enabled can stand alone", async () => {
    mockBaseEndpoints(["core", "items", "locations"]);
    renderFocus();
    expect(
      await screen.findByText(/can be shown on their own/i),
    ).toBeInTheDocument();
    expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
  });

  it("names the apps that could stand alone, with their state and a way to enable each", async () => {
    mockBaseEndpoints(["core", "items", "locations"]);
    renderFocus();
    const empty = await screen.findByTestId("focus-empty");

    // Only what this installation lists, in the catalogue's words.
    const rows = within(empty).getAllByRole("listitem");
    expect(
      rows.map(
        (row) => within(row).getByText(/Equipment|Shopping/).textContent,
      ),
    ).toEqual(["Equipment Tracking", "Shopping Lists"]);
    for (const row of rows) {
      expect(within(row).getByText("Not enabled")).toBeInTheDocument();
    }
    expect(
      within(rows[0]).getByRole("link", {
        name: "Enable Equipment Tracking in the App Store",
      }),
    ).toHaveAttribute("href", "/apps?module=equipment");
    expect(within(empty).queryByText(/standalone/i)).not.toBeInTheDocument();
  });

  it("does not show the empty state once a module can stand alone", async () => {
    mockBaseEndpoints();
    renderFocus();
    await screen.findByRole("checkbox", {
      name: "Show only Equipment Tracking",
    });
    expect(screen.queryByTestId("focus-empty")).not.toBeInTheDocument();
  });

  it("says it in plain words — never the old jargon", async () => {
    mockBaseEndpoints();
    renderFocus();
    await screen.findByRole("checkbox", {
      name: "Show only Equipment Tracking",
    });
    expect(document.body).not.toHaveTextContent(/work mode/i);
    expect(document.body).not.toHaveTextContent(/tryb pracy/i);
  });
});

describe("FocusDiffPreview — the rename group", () => {
  const baseDiff = previewResponse.diff!;
  const describe = () => null;

  it("shows an arrow only for a name this decision really changes", () => {
    render(
      <FocusDiffPreview
        diff={baseDiff}
        renameRows={[
          { key: "inventory:nav.items", current: "Products", next: "Assets" },
        ]}
        describe={describe}
      />,
    );

    expect(screen.getByText("Will be renamed")).toBeInTheDocument();
    expect(screen.getByText("Products")).toBeInTheDocument();
    expect(screen.getByText("Assets")).toBeInTheDocument();
  });

  it("says the names are already set instead of promising X → X", () => {
    // The overrides apply the moment the module is enabled, so
    // current and next were always the same word and the preview showed
    // "Assets → Assets" — a difference that does not exist, next to two
    // groups that do not lie.
    render(
      <FocusDiffPreview
        diff={baseDiff}
        renameRows={[
          { key: "inventory:nav.items", current: "Assets", next: "Assets" },
          {
            key: "inventory:nav.storages",
            current: "Locations",
            next: "Locations",
          },
        ]}
        describe={describe}
      />,
    );

    expect(screen.queryByText("Will be renamed")).not.toBeInTheDocument();
    expect(
      screen.getByText("Already named by the enabled module"),
    ).toBeInTheDocument();
    expect(screen.getByText("Assets")).toBeInTheDocument();
    expect(screen.getByText("Locations")).toBeInTheDocument();
  });
});

it("explains temporary background activation and what showing all does to its data", () => {
  render(
    <FocusDiffPreview
      diff={{
        ...previewResponse.diff!,
        focus_module: "recipes",
        enable: ["shopping_lists"],
      }}
      renameRows={[]}
      describe={(id) => (id === "shopping_lists" ? "Shopping Lists" : null)}
    />,
  );
  expect(
    screen.getByText("Will switch on in the background"),
  ).toBeInTheDocument();
  expect(
    screen.getByText(/Switched off again when you show all modules/),
  ).toHaveTextContent(
    "Switched off again when you show all modules. Your data is kept; enable the module again to see it.",
  );
});
