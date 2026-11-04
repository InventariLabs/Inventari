import { createRef } from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { Checkbox } from "./Checkbox";

describe("Checkbox", () => {
  it("is named by its label and toggles when the label text is clicked", async () => {
    const onChange = vi.fn();
    render(<Checkbox id="agree" label="I agree" onChange={onChange} />);

    await userEvent.click(screen.getByText("I agree"));

    expect(screen.getByRole("checkbox", { name: "I agree" })).toBeChecked();
    expect(onChange).toHaveBeenCalledTimes(1);
  });

  it("renders a bare checkbox when there is no label", () => {
    const { container } = render(<Checkbox aria-label="Select row" />);

    expect(screen.getByRole("checkbox", { name: "Select row" })).toBeVisible();
    expect(container.querySelector("label")).toBeNull();
  });

  it("shows the mixed state of a partial selection and drops it when cleared", () => {
    const { rerender } = render(
      <Checkbox aria-label="Select all" indeterminate onChange={vi.fn()} />,
    );
    expect(
      screen.getByRole("checkbox", { name: "Select all" }),
    ).toBePartiallyChecked();

    rerender(<Checkbox aria-label="Select all" onChange={vi.fn()} />);
    expect(
      screen.getByRole("checkbox", { name: "Select all" }),
    ).not.toBePartiallyChecked();
  });

  it("hands the caller the real input through its ref", () => {
    const ref = createRef<HTMLInputElement>();
    render(<Checkbox ref={ref} aria-label="Pick" />);

    expect(ref.current).toBe(screen.getByRole("checkbox", { name: "Pick" }));
  });

  it("does not toggle while disabled", async () => {
    const onChange = vi.fn();
    render(<Checkbox id="x" label="Locked" disabled onChange={onChange} />);

    await userEvent.click(screen.getByText("Locked"));

    expect(onChange).not.toHaveBeenCalled();
    expect(screen.getByRole("checkbox", { name: "Locked" })).not.toBeChecked();
  });

  it("with touchTarget, a 44px square around the box toggles it on a phone", async () => {
    const onChange = vi.fn();
    render(<Checkbox touchTarget aria-label="Pick" onChange={onChange} />);

    const box = screen.getByRole("checkbox", { name: "Pick" });
    const hit = box.closest("label");
    expect(hit).not.toBeNull();
    expect(hit?.className).toContain("min-h-11");
    expect(hit?.className).toContain("min-w-11");
    expect(hit?.className).toContain("md:min-h-0");

    await userEvent.click(hit as HTMLElement);
    expect(onChange).toHaveBeenCalledTimes(1);
  });

  it("with a label, the whole row is a 44px target on a phone", () => {
    render(<Checkbox id="row" label="Read the team list" />);

    const row = screen
      .getByRole("checkbox", { name: "Read the team list" })
      .closest("label");
    expect(row?.className).toContain("min-h-11");
    expect(row?.className).toContain("md:min-h-0");
  });
});
