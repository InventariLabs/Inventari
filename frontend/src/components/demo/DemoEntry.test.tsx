import { render, screen } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { DemoEntry } from "./DemoEntry";

describe("DemoEntry", () => {
  it("tells the visitor what to keep out of the demo and when it ends", () => {
    render(<DemoEntry onTry={vi.fn()} isOpening={false} failure={null} />);

    // The entry screen carries both halves of the deal: the schedule the
    // copy lives on, and the plain instruction to keep real data out.
    expect(screen.getByText(/wiped every night/i)).toBeInTheDocument();
    expect(screen.getByText(/do not enter real data/i)).toBeInTheDocument();
  });
});
