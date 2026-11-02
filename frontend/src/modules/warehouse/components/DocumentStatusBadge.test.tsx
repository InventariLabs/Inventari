import { describe, expect, it } from "vitest";
import { render, screen } from "@/test/utils";
import { DocumentStatusBadge } from "./DocumentStatusBadge";

describe("DocumentStatusBadge", () => {
  it("renders DRAFT badge", () => {
    render(<DocumentStatusBadge status="DRAFT" />);
    expect(screen.getByText("Draft")).toBeInTheDocument();
  });

  it("renders CONFIRMED badge", () => {
    render(<DocumentStatusBadge status="CONFIRMED" />);
    expect(screen.getByText("Confirmed")).toBeInTheDocument();
  });

  it("renders COMPLETED badge", () => {
    render(<DocumentStatusBadge status="COMPLETED" />);
    expect(screen.getByText("Completed")).toBeInTheDocument();
  });

  it("renders CANCELLED badge", () => {
    render(<DocumentStatusBadge status="CANCELLED" />);
    expect(screen.getByText("Cancelled")).toBeInTheDocument();
  });
});
