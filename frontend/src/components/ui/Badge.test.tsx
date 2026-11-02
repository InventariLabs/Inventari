import { render, screen } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { Badge } from "@/components/ui/Badge";

describe("Badge", () => {
  it("renders children text", () => {
    render(<Badge>New</Badge>);
    expect(screen.getByText("New")).toBeInTheDocument();
  });

  it("fills the default variant on a step that clears AA under a white label", () => {
    // 10px white text needs 4.5:1: primary-600 gives 3.77. The fill takes the
    // primary Button's pair — 700 in light, 800 in dark, where a profile's
    // palette moves 700 to its light shade.
    render(<Badge>Core</Badge>);
    const { className } = screen.getByText("Core");
    expect(className).toContain("bg-primary-700");
    expect(className).toContain("dark:bg-primary-800");
    expect(className).not.toContain("bg-primary-600");
  });

  it("renders an inline element", () => {
    // A badge looks inline and is used inside paragraphs, list text and
    // table cells — a block box in the DOM made every such use invalid
    // HTML and logged validateDOMNesting on the pages that carry one.
    render(<Badge>New</Badge>);
    expect(screen.getByText("New").tagName).toBe("SPAN");
  });

  it("inside a paragraph, it warns nothing", () => {
    const errorSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    try {
      render(
        <p>
          Text <Badge>New</Badge>
        </p>,
      );
      const nesting = errorSpy.mock.calls.filter((call) =>
        String(call[0]).includes("validateDOMNesting"),
      );
      expect(nesting).toEqual([]);
    } finally {
      errorSpy.mockRestore();
    }
  });

  it.each([
    "default",
    "secondary",
    "outline",
    "danger",
    "success",
    "warning",
    "info",
  ] as const)('renders variant "%s" without throwing', (variant) => {
    const { container } = render(<Badge variant={variant}>Label</Badge>);
    expect(container.firstChild).toBeInTheDocument();
  });

  it("passes custom className", () => {
    const { container } = render(<Badge className="extra-class">Badge</Badge>);
    expect(container.firstChild).toHaveClass("extra-class");
  });
});
