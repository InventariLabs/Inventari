import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ChoiceGroup } from "../ChoiceGroup";

const OPTIONS = [
  { id: "GOOD", label: "Good" },
  { id: "DAMAGED", label: "Damaged" },
];

describe("ChoiceGroup", () => {
  it("names the group, so the options are heard as answers to a question", () => {
    render(
      <ChoiceGroup
        label="Condition"
        options={OPTIONS}
        value="GOOD"
        onChange={vi.fn()}
      />,
    );

    expect(screen.getByRole("radiogroup", { name: "Condition" })).toBeVisible();
  });

  it("says which option is the chosen one, not only by colour", () => {
    render(
      <ChoiceGroup
        label="Condition"
        options={OPTIONS}
        value="DAMAGED"
        onChange={vi.fn()}
      />,
    );

    expect(screen.getByRole("radio", { name: "Good" })).toHaveAttribute(
      "aria-checked",
      "false",
    );
    expect(screen.getByRole("radio", { name: "Damaged" })).toHaveAttribute(
      "aria-checked",
      "true",
    );
  });

  it("reports the option that was picked", () => {
    const onChange = vi.fn();
    render(
      <ChoiceGroup
        label="Condition"
        options={OPTIONS}
        value="GOOD"
        onChange={onChange}
      />,
    );

    fireEvent.click(screen.getByRole("radio", { name: "Damaged" }));
    expect(onChange).toHaveBeenCalledWith("DAMAGED");
  });

  it("carries the hint next to the label, where the question is asked", () => {
    render(
      <ChoiceGroup
        label="Condition"
        hint="One condition covers the whole batch."
        options={OPTIONS}
        value="GOOD"
        onChange={vi.fn()}
      />,
    );

    expect(
      screen.getByText("One condition covers the whole batch."),
    ).toBeVisible();
  });

  /**
   * `role="group"` gives `aria-required` no defined meaning, so a required
   * group announced five independent toggles and no requirement at all. The
   * role that carries it also brings the manners: one tab stop, arrows moving
   * the choice.
   */
  it("announces a required group as required", () => {
    render(
      <ChoiceGroup
        label="Type"
        required
        options={OPTIONS}
        value=""
        onChange={vi.fn()}
      />,
    );

    expect(screen.getByRole("radiogroup", { name: /Type/ })).toHaveAttribute(
      "aria-required",
      "true",
    );
  });

  it("holds one tab stop, on the chosen option", () => {
    render(
      <ChoiceGroup
        label="Condition"
        options={OPTIONS}
        value="DAMAGED"
        onChange={vi.fn()}
      />,
    );

    expect(screen.getByRole("radio", { name: "Good" })).toHaveAttribute(
      "tabindex",
      "-1",
    );
    expect(screen.getByRole("radio", { name: "Damaged" })).toHaveAttribute(
      "tabindex",
      "0",
    );
  });

  it("keeps the group reachable when nothing is chosen yet", () => {
    render(
      <ChoiceGroup
        label="Type"
        required
        options={OPTIONS}
        value=""
        onChange={vi.fn()}
      />,
    );

    expect(screen.getByRole("radio", { name: "Good" })).toHaveAttribute(
      "tabindex",
      "0",
    );
  });

  it("moves the choice with the arrow keys", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(
      <ChoiceGroup
        label="Condition"
        options={OPTIONS}
        value="GOOD"
        onChange={onChange}
      />,
    );

    screen.getByRole("radio", { name: "Good" }).focus();
    await user.keyboard("{ArrowRight}");

    expect(onChange).toHaveBeenCalledWith("DAMAGED");
  });

  it("says what is missing instead of leaving the reader with a dead button", () => {
    render(
      <ChoiceGroup
        label="Type"
        required
        error="Choose what kind of work this was"
        options={OPTIONS}
        value=""
        onChange={vi.fn()}
      />,
    );

    expect(screen.getByRole("alert")).toHaveTextContent(
      "Choose what kind of work this was",
    );
    expect(screen.getByRole("radiogroup", { name: /Type/ })).toHaveAttribute(
      "aria-invalid",
      "true",
    );
  });
});
