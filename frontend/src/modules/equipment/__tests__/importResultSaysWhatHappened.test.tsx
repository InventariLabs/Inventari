/**
 * A sheet whose every row was refused closed under a green check and
 * "Import complete", above "Imported: 0, Failed: 3". The headline now
 * follows what the run wrote.
 */
import { describe, expect, it } from "vitest";
import { render, screen } from "@/test/utils";
import { ImportResultSummary } from "@/modules/equipment/components/ImportResultSummary";

const result = (over: Record<string, unknown>) => ({
  imported: 0,
  failed: 0,
  skipped: 0,
  updated: 0,
  errors: [],
  skipped_serials: [],
  ...over,
});

describe("the import result headline", () => {
  it("does not call a run that wrote nothing complete", () => {
    render(
      <ImportResultSummary
        result={result({
          failed: 1,
          errors: [{ row: 2, error: "No location is named “Shelf 9”" }],
        })}
      />,
    );

    expect(screen.getByText("Nothing was imported")).toBeInTheDocument();
    expect(screen.queryByText("Import complete")).not.toBeInTheDocument();
    expect(
      screen.getByText("Row 2: No location is named “Shelf 9”"),
    ).toBeInTheDocument();
  });

  it("calls a run that wrote everything complete", () => {
    render(<ImportResultSummary result={result({ imported: 2 })} />);

    expect(screen.getByText("Import complete")).toBeInTheDocument();
    expect(screen.queryByText("Nothing was imported")).not.toBeInTheDocument();
  });

  it("does not call a run that refused some rows complete", () => {
    render(
      <ImportResultSummary
        result={result({
          imported: 66,
          failed: 2,
          errors: [{ row: 3, error: "Invalid status: Banana" }],
        })}
      />,
    );

    expect(screen.getByText("Import finished with errors")).toBeInTheDocument();
    expect(screen.queryByText("Import complete")).not.toBeInTheDocument();
  });

  it("names the serial numbers it skipped as duplicates", () => {
    render(
      <ImportResultSummary
        result={result({
          imported: 1,
          skipped: 3,
          skipped_serials: ["SN-A", "SN-B"],
        })}
      />,
    );

    expect(
      screen.getByText("Skipped as duplicates: SN-A, SN-B, …"),
    ).toBeInTheDocument();
  });
});
