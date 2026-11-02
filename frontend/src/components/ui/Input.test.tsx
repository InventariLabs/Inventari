import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { Input } from "@/components/ui/Input";

describe("Input", () => {
  it("renders input element", () => {
    render(<Input />);
    expect(screen.getByRole("textbox")).toBeInTheDocument();
  });

  it("renders with label", () => {
    render(<Input id="name" label="Full Name" />);
    expect(screen.getByLabelText("Full Name")).toBeInTheDocument();
  });

  it("associates the label with the input when the caller passes no id", () => {
    render(<Input label="Brand" />);
    expect(screen.getByLabelText("Brand")).toBeInTheDocument();
  });

  it("keeps two inputs apart when neither caller passes an id", () => {
    render(
      <>
        <Input label="Brand" />
        <Input label="Serial Number" />
      </>,
    );
    expect(screen.getByLabelText("Brand")).not.toBe(
      screen.getByLabelText("Serial Number"),
    );
  });

  // requiredness is announced by the control, never spelled "star".
  it("keeps the required star out of the label text", () => {
    render(<Input label="Target Location" required />);
    // The exact match on the label's own text proves the star is not part of
    // it — it is a hidden sibling, so the accessible name is "Target Location"
    // and the reader says "required" from the control, never "star".
    const label = screen.getByText("Target Location");
    expect(label).toBeInTheDocument();
    const input = screen.getByRole("textbox");
    expect(input).toBeRequired();
    expect(input).toHaveAttribute("aria-required", "true");
    const star = screen.getByText("*");
    expect(star).toHaveAttribute("aria-hidden", "true");
  });

  it("marks the field required via aria alone for inline-validating forms", () => {
    render(<Input label="Max" aria-required="true" />);
    const input = screen.getByRole("textbox");
    expect(input).toHaveAttribute("aria-required", "true");
    // No native constraint — the form's own error flow stays in charge.
    expect(input).not.toHaveAttribute("required");
    const star = screen.getByText("*");
    expect(star).toHaveAttribute("aria-hidden", "true");
  });

  it("renders placeholder text", () => {
    render(<Input placeholder="Enter text..." />);
    expect(screen.getByPlaceholderText("Enter text...")).toBeInTheDocument();
  });

  it("displays error message", () => {
    render(<Input error="This field is required" />);
    expect(screen.getByText("This field is required")).toBeInTheDocument();
  });

  it("is disabled when disabled prop is set", () => {
    render(<Input disabled />);
    expect(screen.getByRole("textbox")).toBeDisabled();
  });

  it("renders left and right icons", () => {
    const LeftIcon = () => <span data-testid="left-icon" />;
    const RightIcon = () => <span data-testid="right-icon" />;
    render(<Input leftIcon={<LeftIcon />} rightIcon={<RightIcon />} />);
    expect(screen.getByTestId("left-icon")).toBeInTheDocument();
    expect(screen.getByTestId("right-icon")).toBeInTheDocument();
  });
});
