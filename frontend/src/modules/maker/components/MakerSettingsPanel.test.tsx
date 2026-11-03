import { fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { http, HttpResponse } from "msw";

import { server } from "@/test/mocks/server";
import { signInWith, signOut } from "@/test/auth";
import { MakerSettingsPanel } from "./MakerSettingsPanel";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

// The settings query is gated on the module being enabled; only the reader is
// faked, so the real provider is not needed to answer that.
vi.mock("@/contexts/ModulesContext", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/contexts/ModulesContext")>()),
  useModules: () => ({
    enabledModules: ["maker"],
    isModuleEnabled: (name: string) => name === "maker",
    isLoading: false,
    refreshModules: vi.fn(),
  }),
}));

/**
 * The panel used to draw every switch for an account that could not move one.
 *
 * Measured: a read-only account got the full panel plus the line "Each choice
 * saves as you make it. There is no undo — set it back the same way", and a
 * click on Margin answered 403 with "Failed to save settings" — a sentence
 * about a failure where the truth was a boundary. The neighbouring module got
 * this right: /recipes/settings shows such an account a refusal and no
 * switches at all.
 */
function renderPanel() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MakerSettingsPanel />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  server.resetHandlers();
  server.use(
    http.get("/api/v1/maker/settings", () =>
      HttpResponse.json({
        reference_direction: "SAVINGS",
        allow_overproduction: true,
        availability_check_scope: "GLOBAL",
        create_on_shortage_strategy: "ALLOW",
      }),
    ),
  );
});

afterEach(() => {
  signOut();
});

describe("MakerSettingsPanel", () => {
  it("shows a reader the refusal instead of switches it cannot move", async () => {
    signInWith(["maker:read"]);
    renderPanel();

    // Nothing is shown read-only, so the page must not claim it can be viewed.
    expect(
      await screen.findByText(
        /only an administrator can open module settings/i,
      ),
    ).toBeInTheDocument();
    expect(
      screen.queryByText(/you can view this, not change it/i),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /margin/i }),
    ).not.toBeInTheDocument();
    // The promise that every choice saves itself belongs with the choices.
    expect(screen.queryByText(/there is no undo/i)).not.toBeInTheDocument();
  });

  it("tells a floor worker with write rights that the manager changes the settings", async () => {
    // maker:write is the floor's right — it runs production. The notice used
    // to ask about it, found it granted and drew nothing, so the page was a
    // heading and white space.
    signInWith(["maker:read", "maker:write"]);
    renderPanel();

    expect(
      await screen.findByText(
        /only an administrator can open module settings/i,
      ),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /margin/i }),
    ).not.toBeInTheDocument();
  });

  it("shows the switches to an account that may move them", async () => {
    // Settings are the manager's: a shortage strategy decides what
    // production does to stock, so the panel sits behind maker:manage.
    signInWith(["maker:read", "maker:write", "maker:manage"]);
    renderPanel();

    expect(
      await screen.findByRole("button", { name: /margin/i }),
    ).toBeInTheDocument();
    expect(
      screen.queryByText(/you can view this, not change it/i),
    ).not.toBeInTheDocument();
  });

  /**
   * The rules for shortages and overproduction have defaults that suit a
   * small workshop. Drawn at the weight of the result's name, they read as a
   * form to fill in before the first order; they now wait under Advanced.
   */
  it("keeps the policy switches under Advanced until asked for", async () => {
    signInWith(["maker:read", "maker:write", "maker:manage"]);
    renderPanel();

    // The result's name and what it means are on the first screen.
    expect(
      await screen.findByRole("button", { name: "Savings vs shop price" }),
    ).toBeInTheDocument();
    expect(
      screen.getByTestId("maker-settings-result-definition"),
    ).toHaveTextContent("Shop price minus the cost to make it");
    expect(screen.queryByRole("switch")).not.toBeInTheDocument();
    expect(screen.queryByText("Shortage strategy on create")).toBeNull();

    const advanced = screen.getByRole("button", { name: /advanced/i });
    expect(advanced).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(advanced);
    expect(advanced).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("switch")).toBeInTheDocument();
    expect(screen.getByText("Shortage strategy on create")).toBeInTheDocument();
    expect(screen.getByText("Availability check scope")).toBeInTheDocument();
  });

  /**
   * The switch drew as a 44×24 BUTTON with no text and no
   * aria-label — its name lived only in the heading beside it, so a screen
   * reader landed on an unnamed "switch" between unnamed neighbours.
   */
  it("gives the overproduction switch a name", async () => {
    signInWith(["maker:read", "maker:write", "maker:manage"]);
    renderPanel();

    fireEvent.click(
      await screen.findByRole("button", { name: /advanced/i, expanded: false }),
    );
    const toggle = await screen.findByRole("switch", {
      name: /allow overproduction/i,
    });
    expect(toggle).toHaveAttribute("aria-checked", "true");
  });
});
