import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi } from "vitest";
import { Package, Plus } from "lucide-react";
import { EmptyState, EmptyStateAction } from "./EmptyState";

describe("EmptyState", () => {
  it("renders icon, title, and description", () => {
    render(
      <EmptyState
        icon={Package}
        title="No items yet"
        description="Add your first item to get started"
      />,
    );
    expect(screen.getByTestId("empty-state")).toBeInTheDocument();
    expect(screen.getByText("No items yet")).toBeInTheDocument();
    expect(
      screen.getByText("Add your first item to get started"),
    ).toBeInTheDocument();
  });

  it("renders primary action with click handler", async () => {
    const user = userEvent.setup();
    const onClick = vi.fn();
    render(
      <EmptyState
        title="Empty"
        primaryAction={<EmptyStateAction label="Add now" onClick={onClick} />}
      />,
    );
    await user.click(screen.getByRole("button", { name: /Add now/i }));
    expect(onClick).toHaveBeenCalledTimes(1);
  });

  it("renders numbered steps in 'steps' variant", () => {
    render(
      <EmptyState
        icon={Plus}
        title="Getting started"
        description="Three quick steps"
        variant="steps"
        steps={[
          { title: "Step one", description: "First thing to do" },
          { title: "Step two" },
          { title: "Step three" },
        ]}
      />,
    );
    expect(screen.getByText("Step one")).toBeInTheDocument();
    expect(screen.getByText("First thing to do")).toBeInTheDocument();
    expect(screen.getByText("Step two")).toBeInTheDocument();
    expect(screen.getByText("Step three")).toBeInTheDocument();
    const list = screen.getByRole("list", { name: /Getting started/i });
    expect(list).toBeInTheDocument();
  });

  it("renders compact variant with horizontal layout", () => {
    render(
      <EmptyState
        icon={Package}
        title="Compact title"
        description="Short hint"
        variant="compact"
      />,
    );
    expect(screen.getByText("Compact title")).toBeInTheDocument();
    expect(screen.getByText("Short hint")).toBeInTheDocument();
  });

  it("accepts custom className", () => {
    const { container } = render(
      <EmptyState title="x" className="custom-class" />,
    );
    expect(container.firstChild).toHaveClass("custom-class");
  });

  it("renders without icon when not provided", () => {
    render(<EmptyState title="Headless empty state" />);
    expect(screen.getByText("Headless empty state")).toBeInTheDocument();
  });
});
