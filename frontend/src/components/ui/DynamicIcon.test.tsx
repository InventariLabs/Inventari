import { render } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { DynamicIcon } from "./DynamicIcon";

describe("DynamicIcon", () => {
  it("renders with icon name prop", () => {
    const { container } = render(<DynamicIcon name="Snowflake" />);

    expect(container.firstChild).toBeTruthy();
  });

  it("accepts size prop", () => {
    const { container } = render(<DynamicIcon name="Snowflake" size={32} />);

    expect(container.firstChild).toBeTruthy();
  });

  it("accepts className prop", () => {
    const { container } = render(
      <DynamicIcon name="Snowflake" className="custom-class" />,
    );

    expect(container.firstChild).toBeTruthy();
  });

  it("accepts strokeWidth prop", () => {
    const { container } = render(
      <DynamicIcon name="Snowflake" strokeWidth={3} />,
    );

    expect(container.firstChild).toBeTruthy();
  });

  it("renders multiple icons without conflict", () => {
    const { container } = render(
      <div>
        <DynamicIcon name="Snowflake" />
        <DynamicIcon name="Package" />
        <DynamicIcon name="Settings" />
      </div>,
    );

    const icons = container.querySelectorAll("svg");
    expect(icons.length).toBeGreaterThanOrEqual(1);
  });

  it("renders with all props combined", () => {
    const { container } = render(
      <DynamicIcon
        name="Snowflake"
        size={24}
        className="test-icon"
        strokeWidth={2}
      />,
    );

    expect(container.firstChild).toBeTruthy();
  });
});
