import { fireEvent, render, screen } from "@testing-library/react";
import { describe, it, expect, vi, afterEach } from "vitest";
import { ActionMenu } from "@/components/ui/ActionMenu";

const openMenu = () =>
  fireEvent.click(screen.getByRole("button", { name: "More actions" }));

describe("ActionMenu", () => {
  it("orders destructive actions last, behind a separator", () => {
    render(
      <ActionMenu
        label="More actions"
        actions={[
          {
            id: "delete",
            label: "Delete",
            destructive: true,
            onSelect: vi.fn(),
          },
          { id: "archive", label: "Archive", onSelect: vi.fn() },
        ]}
      />,
    );
    openMenu();

    const labels = screen
      .getAllByRole("button")
      .map((b) => b.textContent)
      .filter((text) => text === "Archive" || text === "Delete");
    expect(labels).toEqual(["Archive", "Delete"]);
    expect(screen.getByRole("separator")).toBeInTheDocument();
  });

  it("draws no separator when nothing destructive is in the menu", () => {
    render(
      <ActionMenu
        label="More actions"
        actions={[{ id: "archive", label: "Archive", onSelect: vi.fn() }]}
      />,
    );
    openMenu();

    expect(screen.queryByRole("separator")).not.toBeInTheDocument();
  });

  it("runs the action and closes", () => {
    const onSelect = vi.fn();
    render(
      <ActionMenu
        label="More actions"
        actions={[{ id: "archive", label: "Archive", onSelect }]}
      />,
    );
    openMenu();
    fireEvent.click(screen.getByRole("button", { name: "Archive" }));

    expect(onSelect).toHaveBeenCalledOnce();
    expect(screen.queryByRole("button", { name: "Archive" })).toBeNull();
  });

  describe("Escape", () => {
    const surfaceListener = vi.fn();
    afterEach(() => {
      document.removeEventListener("keydown", surfaceListener);
      surfaceListener.mockReset();
    });

    /**
     * `Sheet` and `ItemEditModal` close themselves from a `document` keydown
     * listener registered when they mounted — before the menu's. One press
     * used to take the whole editor down with the menu.
     */
    it("closes the menu without reaching the surface that holds it", () => {
      document.addEventListener("keydown", surfaceListener);
      render(
        <ActionMenu
          label="More actions"
          actions={[{ id: "archive", label: "Archive", onSelect: vi.fn() }]}
        />,
      );
      openMenu();
      expect(screen.getByRole("button", { name: "Archive" })).toBeVisible();

      fireEvent.keyDown(document.body, { key: "Escape" });

      expect(screen.queryByRole("button", { name: "Archive" })).toBeNull();
      expect(surfaceListener).not.toHaveBeenCalled();
    });

    it("lets Escape through once the menu is closed", () => {
      document.addEventListener("keydown", surfaceListener);
      render(
        <ActionMenu
          label="More actions"
          actions={[{ id: "archive", label: "Archive", onSelect: vi.fn() }]}
        />,
      );

      fireEvent.keyDown(document.body, { key: "Escape" });

      expect(surfaceListener).toHaveBeenCalledOnce();
    });
  });
});
