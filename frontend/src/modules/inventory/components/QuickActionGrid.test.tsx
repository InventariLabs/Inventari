import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { Package, Trash2 } from "lucide-react";
import { QuickActionGrid } from "./QuickActionGrid";

const actions = [
  {
    id: "consume",
    label: "Remove 1 unit",
    icon: Package,
    color: "text-primary",
    accentBorder: "border-l-primary",
    onClick: vi.fn(),
  },
  {
    id: "add",
    label: "Add 1 unit",
    icon: Package,
    color: "text-primary",
    accentBorder: "border-l-primary",
    onClick: vi.fn(),
  },
  {
    id: "delete",
    label: "Delete",
    icon: Trash2,
    color: "text-danger",
    accentBorder: "border-l-danger",
    onClick: vi.fn(),
    danger: true,
  },
];

describe("QuickActionGrid", () => {
  it("stacks every action as a full-width bar by default, for the narrow sheet", () => {
    render(<QuickActionGrid actions={actions} />);

    const buttons = screen.getAllByRole("button");
    expect(buttons).toHaveLength(3);
    for (const button of buttons) {
      expect(button).toHaveClass("w-full");
    }
    expect(new Set(buttons.map((b) => b.parentElement)).size).toBe(1);
  });

  it("keeps the inline layout full-width below the sm breakpoint and content-wide from it", () => {
    render(<QuickActionGrid actions={actions} layout="inline" />);

    for (const button of screen.getAllByRole("button")) {
      expect(button).toHaveClass("w-full", "sm:w-auto");
    }
  });

  it("sets the destructive action apart from the others in the inline layout", () => {
    render(<QuickActionGrid actions={actions} layout="inline" />);

    const remove = screen.getByRole("button", { name: /Remove 1 unit/ });
    const add = screen.getByRole("button", { name: /Add 1 unit/ });
    const del = screen.getByRole("button", { name: /Delete/ });

    expect(remove.parentElement).toBe(add.parentElement);
    expect(del.parentElement).not.toBe(remove.parentElement);
  });

  it("renders no empty group when no action is destructive", () => {
    render(
      <QuickActionGrid
        actions={actions.filter((a) => !a.danger)}
        layout="inline"
      />,
    );

    expect(screen.getAllByRole("button")).toHaveLength(2);
    const grid = screen.getByRole("button", { name: /Add 1 unit/ })
      .parentElement?.parentElement;
    expect(grid?.children).toHaveLength(1);
  });
});
