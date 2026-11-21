import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@/test/utils";
import { DocumentsGettingStarted } from "./DocumentsGettingStarted";

describe("the first document", () => {
  it("names the receipt with the code this organization numbers it by", () => {
    render(
      <DocumentsGettingStarted onCreateFirst={vi.fn()} receiptCode="PZ" />,
    );

    // The step must not say "receipt (IN)" in an organization whose receipts
    // are PZ: the reader never sees that code anywhere else.
    expect(
      screen.getByText(
        "Start with a receipt (PZ) to register incoming goods from a partner.",
      ),
    ).toBeInTheDocument();
  });
});
