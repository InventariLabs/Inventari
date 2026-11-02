import { describe, it, expect } from "vitest";
import { bulkFailureDetail } from "./bulkOutcome";

const names = new Map([
  ["a-1", "Dell Latitude"],
  ["a-2", "LG Monitor"],
  ["a-3", "Logitech Mouse"],
  ["a-4", "Cisco Switch"],
]);

const more = (count: number) => `and ${count} more`;

describe("what a partly-rejected batch tells the reader", () => {
  it("says nothing when nothing failed", () => {
    expect(bulkFailureDetail([], names, more)).toBeUndefined();
  });

  it("names the asset and the reason", () => {
    const detail = bulkFailureDetail(
      [{ item_id: "a-1", error: "No active assignment" }],
      names,
      more,
    );
    expect(detail).toBe("Dell Latitude — No active assignment");
  });

  it("counts the tail instead of listing everything", () => {
    const detail = bulkFailureDetail(
      [
        { item_id: "a-1", error: "one" },
        { item_id: "a-2", error: "two" },
        { item_id: "a-3", error: "three" },
        { item_id: "a-4", error: "four" },
      ],
      names,
      more,
    );
    expect(detail).toBe(
      "Dell Latitude — one; LG Monitor — two; Logitech Mouse — three; and 1 more",
    );
  });

  it("falls back to the id when the row is not on the page", () => {
    const detail = bulkFailureDetail(
      [{ item_id: "gone", error: "Not found" }],
      names,
      more,
    );
    expect(detail).toBe("gone — Not found");
  });
});
