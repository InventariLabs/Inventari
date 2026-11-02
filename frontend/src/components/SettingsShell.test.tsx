import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useFormGuardStore } from "@/store/formGuardStore";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import SettingsShell from "./SettingsShell";

// Registering the two modules whose settings screens used to be reachable
// only by typing their address: the sidebar builds its module
// entries from the manifests' settingsSections.
import "@/modules/approvals/module";
import "@/modules/stats/module";
// A module whose settings section names a key of its own.
import "@/modules/api_keys/module";

const authState: {
  user: { role: string; is_superuser: boolean; permissions: string[] } | null;
  isAuthenticated: boolean;
  isLoading: boolean;
} = {
  user: { role: "manager", is_superuser: false, permissions: [] },
  isAuthenticated: true,
  isLoading: false,
};

vi.mock("@/store/authStore", () => ({
  useAuthStore: (selector?: (s: typeof authState) => unknown) =>
    selector ? selector(authState) : authState,
}));

const modulesState: { enabledModules: string[] } = {
  enabledModules: ["core", "items"],
};

vi.mock("@/contexts/ModulesContext", () => ({
  useModules: () => ({
    enabledModules: modulesState.enabledModules,
    isModuleEnabled: (name: string) =>
      modulesState.enabledModules.includes(name),
    isLoading: false,
    refreshModules: vi.fn(),
  }),
}));

function renderAt(path: string, role: string, permissions: string[] = []) {
  authState.user = { role, is_superuser: false, permissions };
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/settings" element={<SettingsShell />}>
          <Route index element={<div>general body</div>} />
          <Route path="audit-log" element={<div>audit log body</div>} />
          <Route path="ai" element={<div>ai connections body</div>} />
          <Route path="roles" element={<div>roles body</div>} />
          <Route path="api-keys" element={<div>api keys body</div>} />
          <Route
            path="modules/:name"
            element={<div>module settings body</div>}
          />
        </Route>
      </Routes>
    </MemoryRouter>,
  );
}

describe("SettingsShell access", () => {
  it.each(["manager", "viewer"])(
    "answers %s with a sentence instead of the audit log",
    (role) => {
      // The screen used to be protected by hiding its sidebar link; typing the
      // address rendered it in full and the API then refused the data.
      renderAt("/settings/audit-log", role);

      expect(screen.queryByText("audit log body")).not.toBeInTheDocument();
      expect(
        screen.getByText("This settings screen is for administrators"),
      ).toBeInTheDocument();
    },
  );

  it("closes the child route that used to walk past its parent", () => {
    renderAt("/settings/modules/equipment", "manager");

    expect(screen.queryByText("module settings body")).not.toBeInTheDocument();
    expect(
      screen.getByText("This settings screen is for administrators"),
    ).toBeInTheDocument();
  });

  it("leaves the general section to every member", () => {
    renderAt("/settings", "viewer");

    expect(screen.getByText("general body")).toBeInTheDocument();
  });

  it("links every member to their own profile from the sidebar", () => {
    renderAt("/settings", "viewer");

    const links = screen.getAllByRole("link", { name: "My profile" });
    expect(links.length).toBeGreaterThan(0);
    for (const link of links) {
      expect(link).toHaveAttribute("href", "/settings/profile");
    }
  });

  it("lets an administrator through", () => {
    renderAt("/settings/audit-log", "admin");

    expect(screen.getByText("audit log body")).toBeInTheDocument();
  });

  it("opens the AI connections to a custom role that may change them", () => {
    // The role holds the key the API asks for its five writes. The screen
    // asked for `admin:access` instead, so the grant worked only by API.
    renderAt("/settings/ai", "manager", ["org:settings:write"]);

    expect(screen.getByText("ai connections body")).toBeInTheDocument();
    const links = screen.getAllByRole("link", { name: "AI connections" });
    expect(links.length).toBeGreaterThan(0);
    // The rest of the administration stays closed to that role.
    expect(screen.queryByRole("link", { name: "Audit Log" })).toBeNull();
    expect(screen.queryByRole("link", { name: "Email" })).toBeNull();
  });

  it("keeps the AI connections from a custom role the API refuses", () => {
    // `admin:access` alone: every save on that screen answers 403.
    renderAt("/settings/ai", "manager", ["admin:access"]);

    expect(screen.queryByText("ai connections body")).not.toBeInTheDocument();
    // The role is an administrator's; telling it the screen is for
    // administrators contradicts the gate. The sentence names the key.
    expect(
      screen.queryByText("This settings screen is for administrators"),
    ).toBeNull();
    expect(
      screen.getByText("Your role does not open this settings screen"),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/“Change organization settings”/),
    ).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "AI connections" })).toBeNull();
    expect(
      screen.getAllByRole("link", { name: "Audit Log" }).length,
    ).toBeGreaterThan(0);
  });

  it("names the key the role catalogue asks of a role without it", () => {
    renderAt("/settings/roles", "manager", ["admin:access"]);

    expect(screen.queryByText("roles body")).not.toBeInTheDocument();
    expect(
      screen.getByText("Your role does not open this settings screen"),
    ).toBeInTheDocument();
    expect(screen.getByText(/“System configuration”/)).toBeInTheDocument();
  });

  it("opens the role catalogue to a custom role holding its key", () => {
    renderAt("/settings/roles", "manager", ["system:config:write"]);

    expect(screen.getByText("roles body")).toBeInTheDocument();
    expect(
      screen.getAllByRole("link", { name: "Access & Roles" }).length,
    ).toBeGreaterThan(0);
  });

  it("opens a module section with the key the module names", () => {
    modulesState.enabledModules = ["core", "items", "api_keys"];
    try {
      renderAt("/settings/api-keys", "manager", ["org:settings:write"]);

      expect(screen.getByText("api keys body")).toBeInTheDocument();
      expect(
        screen.getAllByRole("link", { name: "API Keys" }).length,
      ).toBeGreaterThan(0);
    } finally {
      modulesState.enabledModules = ["core", "items"];
    }
  });

  it("links the approvals and stats settings screens from the sidebar", () => {
    // Both screens declare a settings schema and used to be reachable only
    // by typing their address: the settings sidebar builds its module
    // entries from the manifests, and neither module declared one.
    modulesState.enabledModules = ["core", "items", "approvals", "stats"];
    try {
      renderAt("/settings", "admin", ["admin:access"]);

      const approvals = screen.getByRole("link", { name: "Approvals" });
      expect(approvals).toHaveAttribute("href", "/settings/modules/approvals");
      const stats = screen.getByRole("link", { name: "Analytics" });
      expect(stats).toHaveAttribute("href", "/settings/modules/stats");
    } finally {
      modulesState.enabledModules = ["core", "items"];
    }
  });

  it("hides those settings entries when the module is off", () => {
    renderAt("/settings", "admin", ["admin:access"]);

    expect(screen.queryByRole("link", { name: "Approvals" })).toBeNull();
    expect(screen.queryByRole("link", { name: "Analytics" })).toBeNull();
  });

  it("names the mobile section picker with the section it shows", () => {
    renderAt("/settings", "admin", ["admin:access"]);

    // The picker's visible text is the active section's name. A fixed
    // "Settings" aria-label did not contain it, which fails WCAG 2.5.3
    // (label in name) for anyone who says what they see.
    const picker = screen.getByRole("button", { name: "General" });

    expect(picker).toHaveTextContent("General");
    expect(picker).not.toHaveAttribute("aria-label");
  });

  it("gives the mobile header's back control a 44px target", () => {
    renderAt("/settings", "admin", ["admin:access"]);

    // At 390px this one measured 28x44: the default size with its
    // padding cut to `p-1.5`, which leaves a 16px chevron in a 28px box. The
    // header bar is 44px tall either way, so the
    // button takes its full width from `size="icon"` — the glyph stays 16px.
    // It sits immediately before the section picker, which is how the two
    // header bars are told apart here.
    const picker = screen.getByRole("button", { name: "General" });
    const back = within(picker.parentElement as HTMLElement).getByLabelText(
      "Back",
    );

    expect(back.className).toContain("h-11");
    expect(back.className).toContain("w-11");
  });

  it("sticks under the notice strip, in a layer from the z-index system", () => {
    renderAt("/settings", "admin", ["admin:access"]);

    const bar = screen.getByRole("button", { name: "General" })
      .parentElement as HTMLElement;
    expect(bar.className).toContain(
      "top-[calc(3.5rem+var(--app-notice-height,0px))]",
    );
    expect(bar.className).toContain("z-[var(--z-module-nav)]");
    expect(bar.className).not.toMatch(/\bz-\d+\b/);
  });
});

describe("SettingsShell — the mobile nav sheet", () => {
  it("declares itself a dialog and closes on Escape", async () => {
    // The hand-rolled sheet answered no key and declared no role: Escape did
    // nothing and a screen reader met an unnamed surface. The shared Sheet
    // brings both, and the keyboard test is the proof it stayed wired.
    const user = userEvent.setup();
    renderAt("/settings", "admin", ["admin:access"]);

    await user.click(screen.getByRole("button", { name: "General" }));
    expect(screen.getByRole("dialog")).toBeInTheDocument();

    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("gives the sheet's close control a 44px target", async () => {
    // The drawer's X measured 28x44 — the same `p-1.5` idiom the header's
    // back button carried before its own fix. The sheet header renders the
    // close through `size="icon"`, and the size is what this pins.
    const user = userEvent.setup();
    renderAt("/settings", "admin", ["admin:access"]);

    await user.click(screen.getByRole("button", { name: "General" }));
    const close = within(screen.getByRole("dialog")).getByLabelText("Close");
    expect(close.className).toContain("h-11");
    expect(close.className).toContain("w-11");
  });
});

describe("SettingsShell — the sidebar asks before throwing unsaved work away", () => {
  it("asks when a dirty form is registered and cancelling keeps the reader here", async () => {
    const user = userEvent.setup();
    useFormGuardStore.setState({ dirtyForm: "Ustawienia organizacji" });
    renderAt("/settings", "admin");

    await user.click(screen.getByRole("link", { name: /poczta|email/i }));

    const dialog = await screen.findByRole("alertdialog");
    expect(dialog.textContent).toMatch(/Ustawienia organizacji/);

    await user.click(
      within(dialog).getByRole("button", { name: /anuluj|cancel/i }),
    );
    expect(screen.getByText("general body")).toBeInTheDocument();
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();

    useFormGuardStore.setState({ dirtyForm: null });
  });

  it("does not ask when nothing is dirty", async () => {
    const user = userEvent.setup();
    renderAt("/settings", "admin");

    await user.click(screen.getByRole("link", { name: /poczta|email/i }));

    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
  });
});
