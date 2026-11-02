import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { Card, CardFooter, CardTitle } from "@/components/ui/Card";

describe("Card", () => {
  it("renders children", () => {
    render(<Card>Card content</Card>);
    expect(screen.getByText("Card content")).toBeInTheDocument();
  });

  it.each(["default", "elevated", "ghost"] as const)(
    'renders variant "%s" without throwing',
    (variant) => {
      const { container } = render(<Card variant={variant}>Content</Card>);
      expect(container.firstChild).toBeInTheDocument();
    },
  );

  it("lifts on hover when hoverable is true", () => {
    const { container } = render(<Card hoverable>Hoverable</Card>);
    expect(container.firstChild).toHaveClass("hover:shadow-lg");
  });

  /**
   * A pointing cursor is a promise, and the card cannot keep it: whether
   * anything happens on click is the caller's business. One caller had
   * `hoverable` on a card with no action at all, so the cursor said "press
   * me" and pressing did nothing. The cursor belongs to the link the pattern
   * in §2.3a puts on the title.
   */
  it("promises no click of its own", () => {
    const { container } = render(<Card hoverable>Hoverable</Card>);
    expect(container.firstChild).not.toHaveClass("cursor-pointer");
  });

  it("passes custom className", () => {
    const { container } = render(<Card className="custom-class">Text</Card>);
    expect(container.firstChild).toHaveClass("custom-class");
  });
});

describe("CardTitle heading level", () => {
  // The shell owns h1, so a card title is the first level of content. Rendering
  // h3 left a hole in the outline on every screen built from cards.
  it("is h2 by default", () => {
    render(<CardTitle>Lines</CardTitle>);
    expect(screen.getByRole("heading", { level: 2 })).toHaveTextContent(
      "Lines",
    );
  });

  it("drops to h3 when the card is nested in a section of its own", () => {
    render(<CardTitle as="h3">Lines</CardTitle>);
    expect(screen.getByRole("heading", { level: 3 })).toHaveTextContent(
      "Lines",
    );
  });
});

describe("CardFooter", () => {
  it("sets its actions apart from the card body and keeps the caller's props", () => {
    render(
      <CardFooter className="justify-end" data-testid="footer">
        <button type="button">Save</button>
      </CardFooter>,
    );

    const footer = screen.getByTestId("footer");
    expect(footer).toHaveClass("border-t", "justify-end");
    expect(footer).toContainElement(
      screen.getByRole("button", { name: "Save" }),
    );
  });
});
