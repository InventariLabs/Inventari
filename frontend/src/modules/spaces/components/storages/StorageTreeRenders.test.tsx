import { useState } from "react";
import { render } from "@/test/utils";
import { describe, it, expect, vi, beforeEach } from "vitest";
import userEvent from "@testing-library/user-event";
import { StorageTree } from "./StorageTree";
import type { StorageLocationNode } from "@/types";

// Every row draws one slot, so the slot's render count is the row's.
const drawn = vi.hoisted(() => ({ ids: [] as string[] }));
vi.mock("@/components/Slot", () => ({
  TypedSlot: ({ data }: { data: { storageId: string } }) => {
    drawn.ids.push(data.storageId);
    return null;
  },
}));

const ROOTS = 300;

function row(id: string): HTMLElement {
  const found = document.querySelector<HTMLElement>(`[data-tree-node="${id}"]`);
  if (!found) throw new Error(`no row ${id}`);
  return found;
}

function root(index: number): StorageLocationNode {
  return {
    id: `root-${index}`,
    name: `Root ${index}`,
    parent_id: null,
    usage: "internal",
    short_code: null,
    items_count: 0,
    subtree_items_count: 0,
    children_count: 0,
    children: [],
  };
}

const nodes = Array.from({ length: ROOTS }, (_, index) => root(index));

// The callbacks are new functions on every render, the way the page passes
// them: the tree has to cope without asking its parent for stable ones.
function Harness() {
  const [selected, setSelected] = useState<string | undefined>();
  const [expanded] = useState<Set<string>>(new Set());
  return (
    <StorageTree
      nodes={nodes}
      selectedId={selected}
      expanded={expanded}
      onToggle={() => undefined}
      onSelect={(id) => setSelected(id)}
      canWrite
      onMoveTo={() => undefined}
      onOpenSettings={() => undefined}
      onDragMove={() => undefined}
      label="Storage locations"
    />
  );
}

describe("StorageTree — a click on one row", () => {
  beforeEach(() => {
    drawn.ids.length = 0;
  });

  it("redraws the rows whose look changed, not every row of a long level", async () => {
    render(<Harness />);
    expect(drawn.ids).toHaveLength(ROOTS);
    drawn.ids.length = 0;

    await userEvent.click(row("root-7"));
    expect(row("root-7")).toHaveAttribute("aria-selected", "true");
    // The chosen row, plus the one that held the tab stop before.
    expect(drawn.ids.length).toBeLessThanOrEqual(3);

    drawn.ids.length = 0;
    await userEvent.click(row("root-9"));
    expect(drawn.ids.length).toBeLessThanOrEqual(3);
  });
});
