/**
 * regression: the checkout return-date validation speaks the app's
 * language, not the browser's.
 *
 * Previously the field relied on a native `min` attribute — the browser
 * produced its own message ("You must enter a value ... or later") in the
 * browser language. Now the component validates the date and shows an
 * i18n message. The picker no longer offers a past day at all.
 */
import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@/test/utils";
import { CheckoutModal } from "@/modules/equipment/components/CheckoutModal";
import type { Item } from "@/types";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

const mockItem = {
  id: "item-1",
  name: "Dell Laptop",
} as Item;

describe(" checkout return-date validation", () => {
  it("does not offer a past day", () => {
    render(<CheckoutModal item={mockItem} onClose={vi.fn()} />);

    // The picker refuses the days the server refuses, like the attestation
    // deadline picker does: last month is on the grid but cannot be chosen.
    fireEvent.click(
      screen.getByRole("combobox", { name: "Expected Return Date" }),
    );
    fireEvent.click(screen.getByRole("button", { name: "Previous month" }));
    const dayCells = screen.getAllByRole("button", {
      name: /^\w+ \d{1,2}, \d{4}$/,
    });
    expect(dayCells[0]).toBeDisabled();
    fireEvent.click(dayCells[0]);

    // Nothing was chosen, so the field still says what an empty date costs.
    expect(
      screen.getByText(/never appear in the overdue returns report/),
    ).toBeInTheDocument();
  });

  it("accepts today as the return date", async () => {
    render(<CheckoutModal item={mockItem} onClose={vi.fn()} />);

    fireEvent.change(screen.getByPlaceholderText(/name/i), {
      target: { value: "Anna" },
    });
    fireEvent.click(
      screen.getByRole("combobox", { name: "Expected Return Date" }),
    );
    // Today sits on the grid the panel opens on, so it needs no shortcut of
    // its own — the bar above the calendar is for dates the grid cannot reach.
    fireEvent.click(
      document.querySelector('[aria-current="date"]') as HTMLElement,
    );

    expect(
      screen.queryByText("The return date cannot be in the past."),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByText(/never appear in the overdue returns report/),
    ).not.toBeInTheDocument();
  });

  it("says what an empty return date costs", () => {
    render(<CheckoutModal item={mockItem} onClose={vi.fn()} />);

    expect(
      screen.getByText(/never appear in the overdue returns report/),
    ).toBeInTheDocument();
  });
});
