import { describe, expect, it } from "vitest";
import { render, screen } from "@/test/utils";
import { AssetStatusBadge } from "./AssetStatusBadge";

/**
 * A state badge names one of four states, or says there is none.
 *
 * An import wrote whatever the sheet's Status column held, so an asset stood
 * in the list with BANANA in the STATUS column beside AVAILABLE and IN
 * SERVICE, and carried it as its state on the asset card. The import door is
 * shut now; this is the other half — the value is read as an absence, which
 * is what the backend's UNKNOWN_STATUS contract says about a status nobody
 * set.
 */
describe("AssetStatusBadge", () => {
  it("names a state it knows", () => {
    render(<AssetStatusBadge status="MAINTENANCE" />);
    expect(screen.getByText(/in service|maintenance/i)).toBeInTheDocument();
  });

  it("reads a value outside the four as no state, never as a name", () => {
    render(<AssetStatusBadge status="BANANA" />);
    expect(screen.queryByText("BANANA")).not.toBeInTheDocument();
    expect(screen.getByText(/unknown/i)).toBeInTheDocument();
  });

  it("reads the backend's own word for an absent status the same way", () => {
    render(<AssetStatusBadge status="UNKNOWN" />);
    expect(screen.getByText(/unknown/i)).toBeInTheDocument();
  });

  // The metadata reader hands over null when no status exists at all
  // (no equipment namespace in meta_data) — same absence, same answer.
  it("reads a missing status the same way", () => {
    render(<AssetStatusBadge status={null} />);
    expect(screen.getByText(/unknown/i)).toBeInTheDocument();
  });
});
