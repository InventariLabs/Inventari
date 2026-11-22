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
  it("stacks every action as a full-width bar, for the narrow sheet", () => {
    render(<QuickActionGrid actions={actions} />);

    const buttons = screen.getAllByRole("button");
    expect(buttons).toHaveLength(3);
    for (const button of buttons) {
      expect(button).toHaveClass("w-full");
    }
    expect(new Set(buttons.map((b) => b.parentElement)).size).toBe(1);
  });
});
