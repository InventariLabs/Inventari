import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { addDays, format } from "date-fns";
import { PastDayNote } from "./PastDayNote";
import { todayIso } from "@/utils/formatters";

describe("PastDayNote", () => {
  it("says the statements count the recording day once a past day is named", () => {
    const past = format(addDays(new Date(), -3), "yyyy-MM-dd");
    render(<PastDayNote day={past} />);
    const note = screen.getByTestId("maker-past-day-note").textContent;
    expect(note).toContain("on the day it is recorded");
    // Start creates no batch, so the note makes no claim about one.
    expect(note).not.toMatch(/batch/i);
  });

  it("stays silent for today and for an empty field", () => {
    const { rerender } = render(<PastDayNote day={todayIso()} />);
    expect(screen.queryByTestId("maker-past-day-note")).toBeNull();
    rerender(<PastDayNote day="" />);
    expect(screen.queryByTestId("maker-past-day-note")).toBeNull();
  });
});
