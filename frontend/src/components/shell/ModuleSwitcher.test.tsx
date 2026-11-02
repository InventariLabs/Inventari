import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { MemoryRouter, useLocation } from "react-router-dom";
import { Box } from "lucide-react";
import { moduleRegistry, type FrontendModule } from "@/lib/moduleRegistry";
import { useAuthStore } from "@/store/authStore";
import { ModuleSwitcher } from "./ModuleSwitcher";

function makeModule(
  name: string,
  displayName: string,
  opts: { linkTo?: string; basePath?: string; hidden?: boolean } = {},
): FrontendModule {
  return {
    name,
    routes: [],
    launcher: {
      displayName,
      icon: Box,
      linkTo: opts.linkTo,
      hidden: opts.hidden,
    },
    moduleNav: opts.basePath
      ? { basePath: opts.basePath, items: [] }
      : undefined,
  } as unknown as FrontendModule;
}

const equipment = makeModule("equipment", "Equipment", {
  basePath: "/equipment",
});
const documents = makeModule("warehouse", "Warehouse", {
  basePath: "/warehouse",
});
const purchaseOrders = makeModule("purchase_orders", "Purchase Orders", {
  basePath: "/purchase-orders",
});

function LocationProbe() {
  const location = useLocation();
  return <div data-testid="location">{location.pathname}</div>;
}

function renderSwitcher(initialPath = "/equipment") {
  return render(
    <MemoryRouter initialEntries={[initialPath]}>
      <ModuleSwitcher
        activeModule={equipment}
        enabledModules={[
          "equipment",
          "warehouse",
          "purchase_orders",
          "printing",
        ]}
      />
      <LocationProbe />
    </MemoryRouter>,
  );
}

describe("ModuleSwitcher", () => {
  beforeEach(() => {
    moduleRegistry.getVisibleModules = vi.fn(() => [
      equipment,
      documents,
      purchaseOrders,
    ]);
    // Signed out: the footer's target is the question under test, and the
    // administrator case sets its own account.
    useAuthStore.setState({ user: null, isAuthenticated: false });
  });

  it("renders the active module name in the trigger", () => {
    renderSwitcher();
    expect(
      screen.getByRole("button", { name: /switch module/i }),
    ).toHaveTextContent("Equipment");
  });

  /**
   * The trigger shows the module's name, and an `aria-label` of "Switch
   * module" replaced it: a voice user saying the word on screen reached
   * nothing (WCAG 2.5.3). The shown word starts the name now.
   */
  it("starts its accessible name with the module it shows", () => {
    renderSwitcher();
    const trigger = screen.getByRole("button", {
      name: "Equipment Switch module",
    });
    expect(trigger).not.toHaveAttribute("aria-label");
  });

  it("lists visible modules sorted by display name", async () => {
    const user = userEvent.setup();
    renderSwitcher();
    await user.click(screen.getByRole("button", { name: /switch module/i }));

    const items = screen.getAllByRole("menuitem");
    const labels = items.map((i) => i.textContent);
    expect(labels).toEqual([
      "Equipment",
      "Purchase Orders",
      "Warehouse",
      "All modules",
    ]);
    expect(screen.queryByText("Printing")).not.toBeInTheDocument();
  });

  /**
   * jsdom has no layout, so the guard is on the classes that decide it: a
   * fixed-width menu with a `truncate` label cut "Dokumenty magazynowe" to
   * "Dokumenty magazyno…". The menu now grows to its longest name and wraps
   * only when the viewport is narrower than that.
   */
  it("shows a long module name whole instead of ellipsizing it", async () => {
    const user = userEvent.setup();
    renderSwitcher();
    await user.click(screen.getByRole("button", { name: /switch module/i }));

    const menu = screen.getByRole("menu");
    expect(menu).not.toHaveClass("w-56");
    expect(menu).toHaveClass("w-max");
    const label = screen.getByText("Warehouse", {
      selector: "[role=menuitem] span",
    });
    expect(label).not.toHaveClass("truncate");
  });

  it("renders nothing when only one module is visible", () => {
    moduleRegistry.getVisibleModules = vi.fn(() => [equipment]);
    const { container } = render(
      <MemoryRouter initialEntries={["/equipment"]}>
        <ModuleSwitcher
          activeModule={equipment}
          enabledModules={["equipment"]}
        />
      </MemoryRouter>,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("marks the active module with aria-current", async () => {
    const user = userEvent.setup();
    renderSwitcher();
    await user.click(screen.getByRole("button", { name: /switch module/i }));

    const active = screen.getByRole("menuitem", { name: "Equipment" });
    expect(active).toHaveAttribute("aria-current", "page");
    expect(
      screen.getByRole("menuitem", { name: "Warehouse" }),
    ).not.toHaveAttribute("aria-current");
  });

  it("navigates to the module target on click and closes", async () => {
    const user = userEvent.setup();
    renderSwitcher();
    await user.click(screen.getByRole("button", { name: /switch module/i }));
    await user.click(screen.getByRole("menuitem", { name: "Warehouse" }));

    expect(screen.getByTestId("location")).toHaveTextContent("/warehouse");
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
  });

  it("closes on outside click", async () => {
    const user = userEvent.setup();
    renderSwitcher();
    await user.click(screen.getByRole("button", { name: /switch module/i }));
    expect(screen.getByRole("menu")).toBeInTheDocument();

    await user.click(document.body);
    await waitFor(() =>
      expect(screen.queryByRole("menu")).not.toBeInTheDocument(),
    );
  });

  it("closes on Escape", async () => {
    const user = userEvent.setup();
    renderSwitcher();
    await user.click(screen.getByRole("button", { name: /switch module/i }));
    await user.keyboard("{Escape}");

    await waitFor(() =>
      expect(screen.queryByRole("menu")).not.toBeInTheDocument(),
    );
  });

  it("links a member's footer to the launcher", async () => {
    const user = userEvent.setup();
    renderSwitcher();
    await user.click(screen.getByRole("button", { name: /switch module/i }));
    await user.click(screen.getByRole("menuitem", { name: /all modules/i }));

    expect(screen.getByTestId("location")).toHaveTextContent("/launcher");
  });

  it("links an administrator's footer to the screen that chooses modules", async () => {
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
    const user = userEvent.setup();
    renderSwitcher();
    await user.click(screen.getByRole("button", { name: /switch module/i }));
    await user.click(screen.getByRole("menuitem", { name: /my modules/i }));

    expect(screen.getByTestId("location")).toHaveTextContent(
      "/settings/my-modules",
    );
  });
});
