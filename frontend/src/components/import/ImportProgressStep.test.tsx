import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { ImportProgressStep } from "./ImportProgressStep";
import type { ImportOutcome } from "./types";

const texts = {
  waitText: "Please wait while we process your products.",
  addedText: (count: number) => `Added ${count} products.`,
};

describe("ImportProgressStep", () => {
  it("renders loading state", () => {
    render(
      <ImportProgressStep isProcessing={true} importResult={null} {...texts} />,
    );
    expect(screen.getByText("Importing Data…")).toBeInTheDocument();
    expect(
      screen.getByText(/Please wait while we process/),
    ).toBeInTheDocument();
  });

  it("shows how many rows a long import has got through", () => {
    render(
      <ImportProgressStep
        isProcessing={true}
        importResult={null}
        progress={{ processed: 300, total: 1200 }}
        {...texts}
      />,
    );
    const bar = screen.getByRole("progressbar");
    expect(bar).toHaveAttribute("aria-valuenow", "25");
    expect(screen.getByText("Rows: 300 / 1200")).toBeInTheDocument();
  });

  it("shows no bar until the server has reported a count", () => {
    render(
      <ImportProgressStep
        isProcessing={true}
        importResult={null}
        progress={null}
        {...texts}
      />,
    );
    expect(screen.queryByRole("progressbar")).not.toBeInTheDocument();
  });

  it("renders completed result with the server's numbers", () => {
    const mockResult: ImportOutcome = {
      total: 5,
      imported: 5,
      failed: 0,
      errors: [],
    };

    render(
      <ImportProgressStep
        isProcessing={false}
        importResult={mockResult}
        {...texts}
      />,
    );

    expect(screen.getByText("Import complete")).toBeInTheDocument();
    expect(screen.getByText("Added 5 products.")).toBeInTheDocument();
    // TOTAL and IMPORTED tiles both read the server's fields, not a
    // phantom `count`.
    expect(screen.getAllByText("5").length).toBeGreaterThanOrEqual(2);
  });

  it("names every refused row with its reason", () => {
    const mockResult: ImportOutcome = {
      total: 7,
      imported: 5,
      failed: 2,
      errors: [
        { row: 2, error: "Error 1" },
        { row: 4, error: "Error 2" },
      ],
    };

    render(
      <ImportProgressStep
        isProcessing={false}
        importResult={mockResult}
        {...texts}
      />,
    );

    expect(screen.getByText("First few errors")).toBeInTheDocument();
    expect(screen.getByText("Error 1")).toBeInTheDocument();
    expect(screen.getByText("Error 2")).toBeInTheDocument();
    expect(screen.getByText("#2:")).toBeInTheDocument();
    expect(screen.getByText("#4:")).toBeInTheDocument();
  });

  it("displays stats grid from total/imported/failed", () => {
    const mockResult: ImportOutcome = {
      total: 6,
      imported: 5,
      failed: 1,
      errors: [{ row: 3, error: "Error 1" }],
    };

    render(
      <ImportProgressStep
        isProcessing={false}
        importResult={mockResult}
        {...texts}
      />,
    );

    expect(screen.getByText("Total")).toBeInTheDocument();
    expect(screen.getByText("Imported")).toBeInTheDocument();
    expect(screen.getByText("Failed")).toBeInTheDocument();
    expect(screen.getByText("6")).toBeInTheDocument();
    expect(screen.getByText("5")).toBeInTheDocument();
    expect(screen.getByText("1")).toBeInTheDocument();
  });

  it("shows what the entity founded between the counts and the errors", () => {
    const mockResult: ImportOutcome = {
      total: 2,
      imported: 2,
      failed: 0,
      errors: [],
    };

    render(
      <ImportProgressStep
        isProcessing={false}
        importResult={mockResult}
        {...texts}
      >
        <p>2 locations created</p>
      </ImportProgressStep>,
    );

    expect(screen.getByText("2 locations created")).toBeInTheDocument();
  });

  it("takes the entity's summary when it counts more than additions", () => {
    const mockResult: ImportOutcome = {
      total: 3,
      imported: 1,
      failed: 0,
      errors: [],
    };

    render(
      <ImportProgressStep
        isProcessing={false}
        importResult={mockResult}
        summaryText="2 products updated · Added 1 product."
        {...texts}
      />,
    );

    expect(
      screen.getByText("2 products updated · Added 1 product."),
    ).toBeInTheDocument();
    expect(screen.queryByText("Added 1 products.")).not.toBeInTheDocument();
  });

  it("returns null when not processing and no result", () => {
    const { container } = render(
      <ImportProgressStep
        isProcessing={false}
        importResult={null}
        {...texts}
      />,
    );

    expect(container.firstChild).toBeNull();
  });

  // Colour classes cannot be measured in jsdom, so these pin which token
  // carries the text: the status tints flip to dark fills in dark mode, and a
  // ramp step on top of one (accent-400, red-700) was 1.8-2.5:1 there.
  it("reads the result boxes with the text half of their status pair", () => {
    const mockResult: ImportOutcome = {
      total: 7,
      imported: 5,
      failed: 2,
      errors: [{ row: 2, error: "Error 1" }],
    };

    render(
      <ImportProgressStep
        isProcessing={false}
        importResult={mockResult}
        {...texts}
      />,
    );

    expect(screen.getByText("Imported")).toHaveClass("text-on-success");
    expect(screen.getByText("5", { selector: "p" })).toHaveClass(
      "text-on-success",
    );
    expect(screen.getByText("Error 1").closest("li")).toHaveClass(
      "text-on-danger",
    );
  });
});
