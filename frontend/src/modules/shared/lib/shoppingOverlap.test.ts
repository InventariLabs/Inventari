import { describe, expect, it } from "vitest";
import { onOtherListsMessage } from "./shoppingOverlap";

// Plain stand-ins for the two sentences, so what is asserted is the grouping.
const t = (key: string, opts?: Record<string, unknown>) =>
  key.endsWith("onList")
    ? `${opts?.names} @ ${opts?.list}`
    : `TOAST ${opts?.where}`;

describe("onOtherListsMessage", () => {
  it("is null when no other list holds the goods", () => {
    expect(onOtherListsMessage(t, [])).toBeNull();
    expect(onOtherListsMessage(t, undefined)).toBeNull();
  });

  it("says which goods stand on which list, each name once", () => {
    const message = onOtherListsMessage(t, [
      { name: "Flour", list_id: "a", list_name: "A" },
      { name: "Eggs", list_id: "a", list_name: "A" },
      { name: "Eggs", list_id: "a", list_name: "A" },
      { name: "Eggs", list_id: "b", list_name: "B" },
    ]);

    expect(message).toBe("TOAST Flour, Eggs @ A; Eggs @ B");
  });
});
