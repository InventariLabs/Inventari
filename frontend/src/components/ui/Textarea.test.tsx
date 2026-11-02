import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { Textarea } from "@/components/ui/Textarea";

describe("Textarea", () => {
  it("renders a textarea", () => {
    render(<Textarea />);
    expect(screen.getByRole("textbox")).toBeInTheDocument();
  });

  it("associates the label with the textarea when the caller passes no id", () => {
    render(<Textarea label="Description / Notes" />);
    expect(screen.getByLabelText("Description / Notes")).toBeInTheDocument();
  });

  it("honours an id supplied by the caller", () => {
    render(<Textarea id="notes" label="Notes" />);
    expect(screen.getByLabelText("Notes")).toHaveAttribute("id", "notes");
  });

  it("displays an error message", () => {
    render(<Textarea error="This field is required" />);
    expect(screen.getByText("This field is required")).toBeInTheDocument();
  });
});
