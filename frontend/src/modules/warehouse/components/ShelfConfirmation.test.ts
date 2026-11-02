import { describe, expect, it } from "vitest";
import { shelfConfirmationState } from "./ShelfConfirmation";

describe("shelfConfirmationState", () => {
  it("is null while the session does not ask for the shelf label", () => {
    expect(
      shelfConfirmationState({ shelf_scan_required: false }, "shelf-a"),
    ).toBeNull();
    expect(shelfConfirmationState(null, "shelf-a")).toBeNull();
  });

  it("is null for a line that names no shelf", () => {
    expect(
      shelfConfirmationState({ shelf_scan_required: true }, null),
    ).toBeNull();
  });

  it("is to-scan until the line's own shelf is the confirmed one", () => {
    const session = {
      shelf_scan_required: true,
      confirmed_shelf_id: "shelf-b",
    };
    expect(shelfConfirmationState(session, "shelf-a")).toBe("toScan");
    expect(
      shelfConfirmationState(
        { ...session, confirmed_shelf_id: "shelf-a" },
        "shelf-a",
      ),
    ).toBe("confirmed");
  });
});
