import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { SelectionToolbar } from "@/components/ui/SelectionToolbar";

/**
 * "Select all" over a paginated list takes the page, not the result. The bar
 * then read "50 selected" — true of the page, false of the 150 rows the filter
 * matched — and the difference only surfaced during a bulk edit.
 */
describe("SelectionToolbar", () => {
  it("says the selection is of this page when the result is larger", () => {
    render(
      <SelectionToolbar count={50} totalBeyondPage={150} onClear={vi.fn()}>
        <button>Edit</button>
      </SelectionToolbar>,
    );

    expect(
      screen.getByText("50 selected on this page of 150"),
    ).toBeInTheDocument();
  });

  it("says plainly how many when the selection covers everything", () => {
    render(
      <SelectionToolbar count={12} totalBeyondPage={12} onClear={vi.fn()}>
        <button>Edit</button>
      </SelectionToolbar>,
    );

    expect(screen.getByText("12 selected")).toBeInTheDocument();
  });

  it("says plainly how many when nobody said what the result holds", () => {
    render(
      <SelectionToolbar count={3} onClear={vi.fn()}>
        <button>Edit</button>
      </SelectionToolbar>,
    );

    expect(screen.getByText("3 selected")).toBeInTheDocument();
  });
});
