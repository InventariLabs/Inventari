import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useState } from "react";
import { describe, it, expect, vi, afterEach } from "vitest";
import { ActionMenu } from "@/components/ui/ActionMenu";
import { Sheet } from "@/components/ui/Sheet";

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
     * must not take the whole editor down with the menu.
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

  /**
   * The item that opened a sheet unmounts with the menu, so the sheet has no
   * element of the page to give the focus back to when it closes.
   */
  it("hands the focus back to its button when a sheet it opened closes", async () => {
    function Page() {
      const [open, setOpen] = useState(false);
      return (
        <>
          <ActionMenu
            label="More actions"
            actions={[
              { id: "view", label: "View", onSelect: () => setOpen(true) },
            ]}
          />
          <Sheet open={open} onClose={() => setOpen(false)} aria-label="Detail">
            <button onClick={() => setOpen(false)}>Done</button>
          </Sheet>
        </>
      );
    }
    render(<Page />);
    const trigger = screen.getByRole("button", { name: "More actions" });
    openMenu();
    fireEvent.click(screen.getByRole("button", { name: "View" }));
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Done" })).toHaveFocus(),
    );

    fireEvent.click(screen.getByRole("button", { name: "Done" }));

    await waitFor(() => expect(trigger).toHaveFocus());
  });
});
