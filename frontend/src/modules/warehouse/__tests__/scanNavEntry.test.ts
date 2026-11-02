import { describe, expect, it } from "vitest";
import { moduleRegistry } from "@/lib/moduleRegistry";
import "../module";

// A USB scanner sits at a desktop, but scanning in the flow is a button in
// each action there; the document Scan screen is a destination of its own on
// a phone, where it is the middle tab, and one link away from Start on a
// desktop.
describe("the Scan entry in the warehouse module menu", () => {
  const item = moduleRegistry
    .getModule("warehouse")
    ?.moduleNav?.items.find((i) => i.path === "/warehouse/scan");

  it("is the middle tab of a phone", () => {
    expect(item).toBeDefined();
    expect(item?.showOnMobile).not.toBe(false);
    expect(item?.mobileBar).toBe(true);
    expect(item?.mobileOrder).toBe(20);
  });

  it("does not take a desktop tab", () => {
    expect(item?.showOnDesktop).toBe(false);
  });
});
