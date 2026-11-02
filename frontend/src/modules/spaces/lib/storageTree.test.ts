import { describe, expect, it } from "vitest";
import type { StorageLocationNode } from "@/types";
import { descendantIdsOf } from "./storageTree";

const node = (
  id: string,
  children: StorageLocationNode[] = [],
): StorageLocationNode => ({
  id,
  name: id,
  parent_id: null,
  usage: "internal",
  location_type_id: null,
  short_code: null,
  context_tag: null,
  items_count: 0,
  subtree_items_count: 0,
  children_count: children.length,
  children,
});

describe("descendantIdsOf", () => {
  const tree = [
    node("home", [
      node("pantry", [node("shelf"), node("bin")]),
      node("garage"),
    ]),
    node("attic"),
  ];

  it("names everything below a place at any depth, but not the place itself, so a move into it can be refused", () => {
    expect([...descendantIdsOf(tree, "home")].sort()).toEqual([
      "bin",
      "garage",
      "pantry",
      "shelf",
    ]);
  });

  it("is empty for a place with nothing inside and for an id the tree does not hold", () => {
    expect(descendantIdsOf(tree, "attic").size).toBe(0);
    expect(descendantIdsOf(tree, "missing").size).toBe(0);
  });
});
