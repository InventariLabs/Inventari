import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { AllergenPicker } from "./AllergenPicker";

describe("AllergenPicker", () => {
  it("shows 'no allergens' state and opens the 14-key grid", () => {
    render(<AllergenPicker value={[]} onChange={vi.fn()} />);
    expect(
      screen.getByRole("button", { name: /allergens/i }),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /allergens/i }));
    // A few of the 14 EU allergens are visible
    expect(screen.getByText("Milk")).toBeInTheDocument();
    expect(screen.getByText("Gluten")).toBeInTheDocument();
    expect(screen.getByText("Peanuts")).toBeInTheDocument();
  });

  it("says the allergens are suggestions to check against the label", () => {
    render(<AllergenPicker value={[]} onChange={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: /allergens/i }));
    expect(
      screen.getByText(
        "Suggested from ingredient names; may be incomplete. Check the label of each product used.",
      ),
    ).toBeInTheDocument();
  });

  it("toggles an allergen and reports changes", () => {
    const onChange = vi.fn();
    render(<AllergenPicker value={[]} onChange={onChange} />);
    fireEvent.click(screen.getByRole("button", { name: /allergens/i }));
    fireEvent.click(screen.getByLabelText("Milk"));
    expect(onChange).toHaveBeenCalledWith(["milk"]);
  });

  it("removes an allergen from the selected list", () => {
    const onChange = vi.fn();
    render(<AllergenPicker value={["milk", "gluten"]} onChange={onChange} />);
    fireEvent.click(screen.getByRole("button", { name: /allergens/i }));
    fireEvent.click(screen.getByLabelText("Milk"));
    expect(onChange).toHaveBeenCalledWith(["gluten"]);
  });
});
