import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { ThemeToggle } from "@/components/ThemeToggle";
import { useThemeStore } from "@/store/themeStore";

function stubPrefersDark(dark: boolean) {
  vi.stubGlobal(
    "matchMedia",
    vi.fn(() => ({
      matches: dark,
      media: "(prefers-color-scheme: dark)",
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    })),
  );
}

describe("ThemeToggle", () => {
  beforeEach(() => {
    stubPrefersDark(false);
    useThemeStore.setState({ mode: "system", resolved: "light" });
    document.documentElement.classList.remove("dark");
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("names the state it is in, not just 'Theme'", () => {
    // The accessible name used to be a bare "Theme" for both positions, so the
    // button said nothing about which one it was in.
    render(<ThemeToggle />);
    expect(
      screen.getByRole("button", { name: "Theme: Follow system" }),
    ).toBeInTheDocument();
  });

  it("offers the three modes with the active one marked", async () => {
    useThemeStore.setState({ mode: "light", resolved: "light" });
    render(<ThemeToggle />);

    await userEvent.click(screen.getByRole("button"));

    const menu = screen.getByRole("menu");
    expect(within(menu).getAllByRole("menuitemradio")).toHaveLength(3);
    expect(
      within(menu).getByRole("menuitemradio", { name: /light/i }),
    ).toBeChecked();
    expect(
      within(menu).getByRole("menuitemradio", { name: /dark/i }),
    ).not.toBeChecked();
  });

  /**
   * What the picker replaced: a button that cycled light → dark → system. With
   * a light system, two of those three render the same screen, so one step in
   * three changed nothing visible and read as a broken button. A list says
   * which one is chosen instead of asking the reader to know the order.
   */
  it("moves the mark to the mode that was chosen", async () => {
    render(<ThemeToggle />);

    await userEvent.click(screen.getByRole("button"));
    await userEvent.click(screen.getByRole("menuitemradio", { name: /dark/i }));

    expect(useThemeStore.getState().mode).toBe("dark");
    expect(
      screen.getByRole("button", { name: "Theme: Dark" }),
    ).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button"));
    expect(screen.getByRole("menuitemradio", { name: /dark/i })).toBeChecked();
  });

  it("closes the list once a choice is made", async () => {
    render(<ThemeToggle />);

    await userEvent.click(screen.getByRole("button"));
    await userEvent.click(
      screen.getByRole("menuitemradio", { name: /light/i }),
    );

    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
  });

  it("follows a dark system when the following mode is chosen", async () => {
    stubPrefersDark(true);
    useThemeStore.setState({ mode: "light", resolved: "light" });
    render(<ThemeToggle />);

    await userEvent.click(screen.getByRole("button"));
    await userEvent.click(
      screen.getByRole("menuitemradio", { name: /follow system/i }),
    );

    expect(document.documentElement).toHaveClass("dark");
  });

  it("falls back to system when the stored mode is not one it knows", () => {
    // A value left by an older build must not render a blank icon.
    useThemeStore.setState({
      mode: "sepia" as unknown as "system",
      resolved: "light",
    });
    render(<ThemeToggle />);

    expect(
      screen.getByRole("button", { name: "Theme: Follow system" }),
    ).toBeInTheDocument();
  });
});
