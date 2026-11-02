import { describe, it, expect, beforeEach } from "vitest";
import {
  addRecentItem,
  getRecentItems,
  clearRecentItems,
  type RecentItem,
} from "../recentItems";

function makeItem(overrides: Partial<RecentItem> = {}): RecentItem {
  return {
    id: "item-1",
    title: "Test Item",
    module: "inventory",
    path: "/inventory/items/item-1",
    timestamp: Date.now(),
    ...overrides,
  };
}

describe("recentItems", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it("adds an item and retrieves it", () => {
    const item = makeItem();
    addRecentItem(item, "user-1", "org-1");
    const result = getRecentItems("user-1", "org-1");
    expect(result).toHaveLength(1);
    expect(result[0].id).toBe("item-1");
  });

  it("returns empty array when nothing stored", () => {
    expect(getRecentItems("user-1", "org-1")).toEqual([]);
  });

  it("deduplicates same id — replaces with latest", () => {
    addRecentItem(makeItem({ title: "First" }), "user-1", "org-1");
    addRecentItem(makeItem({ title: "Second" }), "user-1", "org-1");
    const result = getRecentItems("user-1", "org-1");
    expect(result).toHaveLength(1);
    expect(result[0].title).toBe("Second");
  });

  it("most recent item is first (prepend)", () => {
    addRecentItem(makeItem({ id: "a", title: "A" }), "user-1", "org-1");
    addRecentItem(makeItem({ id: "b", title: "B" }), "user-1", "org-1");
    const result = getRecentItems("user-1", "org-1");
    expect(result[0].id).toBe("b");
    expect(result[1].id).toBe("a");
  });

  it("enforces FIFO max of 20 items", () => {
    for (let i = 0; i < 25; i++) {
      addRecentItem(makeItem({ id: "item-" + i }), "user-1", "org-1");
    }
    const result = getRecentItems("user-1", "org-1");
    expect(result).toHaveLength(20);
    expect(result[0].id).toBe("item-24");
    expect(result[19].id).toBe("item-5");
  });

  it("is tenant-isolated: different org sees different items", () => {
    addRecentItem(makeItem({ id: "x", title: "Org1 item" }), "user-1", "org-1");
    addRecentItem(makeItem({ id: "y", title: "Org2 item" }), "user-1", "org-2");
    expect(getRecentItems("user-1", "org-1")[0].id).toBe("x");
    expect(getRecentItems("user-1", "org-2")[0].id).toBe("y");
  });

  it("is tenant-isolated: different user sees different items", () => {
    addRecentItem(makeItem({ id: "x" }), "user-1", "org-1");
    addRecentItem(makeItem({ id: "y" }), "user-2", "org-1");
    expect(getRecentItems("user-1", "org-1")[0].id).toBe("x");
    expect(getRecentItems("user-2", "org-1")[0].id).toBe("y");
  });

  it("clearRecentItems removes all entries for a user across orgs", () => {
    addRecentItem(makeItem({ id: "a" }), "user-1", "org-1");
    addRecentItem(makeItem({ id: "b" }), "user-1", "org-2");
    addRecentItem(makeItem({ id: "c" }), "user-2", "org-1");

    clearRecentItems("user-1");

    expect(getRecentItems("user-1", "org-1")).toEqual([]);
    expect(getRecentItems("user-1", "org-2")).toEqual([]);
    expect(getRecentItems("user-2", "org-1")).toHaveLength(1);
  });
});
