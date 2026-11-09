import { useState } from "react";
import { render, screen, fireEvent } from "@/test/utils";
import { describe, it, expect, vi } from "vitest";
import userEvent from "@testing-library/user-event";
import { StorageTree } from "./StorageTree";
import type { StorageLocationNode } from "@/types";

const nodes: StorageLocationNode[] = [
  {
    id: "site",
    name: "Pantry Building",
    parent_id: null,
    usage: "internal",
    short_code: "PB",
    items_count: 0,
    subtree_items_count: 4,
    children_count: 0,
    children: [
      {
        id: "zone",
        name: "Dry Goods",
        parent_id: "site",
        usage: "internal",
        short_code: "DG",
        items_count: 1,
        subtree_items_count: 4,
        children_count: 0,
        children: [
          {
            id: "leaf",
            name: "Shelf A",
            parent_id: "zone",
            usage: "internal",
            short_code: "SA",
            items_count: 3,
            subtree_items_count: 3,
            children_count: 0,
            children: [
              {
                id: "bin",
                name: "Bin 1",
                parent_id: "leaf",
                usage: "internal",
                short_code: "B1",
                items_count: 0,
                subtree_items_count: 0,
                children_count: 0,
                children: [],
              },
            ],
          },
          {
            id: "shelf-b",
            name: "Shelf B",
            parent_id: "zone",
            usage: "internal",
            short_code: "SB",
            items_count: 0,
            subtree_items_count: 0,
            children_count: 0,
            children: [],
          },
        ],
      },
    ],
  },
  {
    id: "freezer",
    name: "Freezer",
    parent_id: null,
    usage: "internal",
    short_code: "FZ",
    items_count: 0,
    subtree_items_count: 0,
    children_count: 0,
    children: [],
  },
];

function Harness({ open = [] }: { open?: string[] }) {
  const [expanded, setExpanded] = useState<Set<string>>(new Set(open));
  const [selected, setSelected] = useState<string | undefined>();
  return (
    <StorageTree
      nodes={nodes}
      selectedId={selected}
      expanded={expanded}
      onToggle={(id) =>
        setExpanded((prev) => {
          const next = new Set(prev);
          if (next.has(id)) next.delete(id);
          else next.add(id);
          return next;
        })
      }
      onSelect={setSelected}
      canWrite={false}
      onMoveTo={vi.fn()}
      onOpenSettings={vi.fn()}
      onDragMove={vi.fn()}
      label="Storage locations"
    />
  );
}

describe("StorageTree — tree semantics", () => {
  it("exposes the tree, its rows and which one is selected", async () => {
    render(<Harness />);

    const tree = screen.getByRole("tree", { name: "Storage locations" });
    expect(tree).toBeInTheDocument();

    const site = screen.getByRole("treeitem", { name: /Pantry Building/ });
    expect(site).toHaveAttribute("aria-level", "1");
    expect(site).toHaveAttribute("aria-expanded", "false");
    expect(site).toHaveAttribute("aria-selected", "false");
    // A leaf says nothing about expanding.
    await userEvent.click(
      screen.getByRole("button", { name: "Expand Pantry Building" }),
    );
    const zone = screen.getByRole("treeitem", { name: /Dry Goods/ });
    expect(zone).toHaveAttribute("aria-level", "2");
  });

  it("moves between rows with the arrow keys and selects with Enter", async () => {
    render(<Harness />);

    const site = screen.getByRole("treeitem", { name: /Pantry Building/ });
    site.focus();
    expect(site).toHaveFocus();

    fireEvent.keyDown(site, { key: "ArrowDown" });
    const freezer = screen.getByRole("treeitem", { name: /Freezer/ });
    expect(freezer).toHaveFocus();

    fireEvent.keyDown(freezer, { key: "ArrowUp" });
    expect(site).toHaveFocus();

    fireEvent.keyDown(site, { key: "Enter" });
    expect(site).toHaveAttribute("aria-selected", "true");
  });

  it("opens a branch with ArrowRight and folds it with ArrowLeft", async () => {
    render(<Harness />);

    const site = screen.getByRole("treeitem", { name: /Pantry Building/ });
    site.focus();
    fireEvent.keyDown(site, { key: "ArrowRight" });
    expect(site).toHaveAttribute("aria-expanded", "true");
    expect(
      screen.getByRole("treeitem", { name: /Dry Goods/ }),
    ).toBeInTheDocument();

    fireEvent.keyDown(site, { key: "ArrowLeft" });
    expect(site).toHaveAttribute("aria-expanded", "false");
    expect(
      screen.queryByRole("treeitem", { name: /Dry Goods/ }),
    ).not.toBeInTheDocument();
  });

  it("takes ArrowLeft from any child to its parent, past expanded siblings", async () => {
    render(<Harness />);

    const site = screen.getByRole("treeitem", { name: /Pantry Building/ });
    site.focus();
    fireEvent.keyDown(site, { key: "ArrowRight" });
    const zone = screen.getByRole("treeitem", { name: /Dry Goods/ });
    fireEvent.keyDown(zone, { key: "ArrowRight" });
    const shelfA = screen.getByRole("treeitem", { name: /Shelf A/ });
    fireEvent.keyDown(shelfA, { key: "ArrowRight" });
    expect(screen.getByRole("treeitem", { name: /Bin 1/ })).toBeInTheDocument();

    // Shelf B follows its sibling's open subtree: the row above it is Bin 1.
    const shelfB = screen.getByRole("treeitem", { name: /Shelf B/ });
    shelfB.focus();
    fireEvent.keyDown(shelfB, { key: "ArrowLeft" });
    expect(zone).toHaveFocus();
  });

  it("takes ArrowLeft from a leaf straight to its parent even when the leaf is in the expanded set", () => {
    // Selecting a leaf, or finding it by search, adds it to `expanded`.
    render(<Harness open={["site", "zone", "shelf-b"]} />);

    const zone = screen.getByRole("treeitem", { name: /Dry Goods/ });
    const shelfB = screen.getByRole("treeitem", { name: /Shelf B/ });
    expect(shelfB).not.toHaveAttribute("aria-expanded");
    shelfB.focus();
    fireEvent.keyDown(shelfB, { key: "ArrowLeft" });
    expect(zone).toHaveFocus();
  });
});

describe("StorageTree — branches that have not been read yet", () => {
  it("shows a row the server says has places inside, before they arrive", async () => {
    const onToggle = vi.fn();
    render(
      <StorageTree
        nodes={[
          {
            id: "wh",
            name: "Warehouse",
            parent_id: null,
            usage: "internal",
            short_code: null,
            items_count: 0,
            subtree_items_count: 40,
            children_count: 12,
            children: [],
          },
        ]}
        expanded={new Set()}
        onToggle={onToggle}
        onSelect={vi.fn()}
        canWrite={false}
        onMoveTo={vi.fn()}
        onOpenSettings={vi.fn()}
        onDragMove={vi.fn()}
        label="Storage locations"
      />,
    );

    expect(screen.getByRole("treeitem", { name: /Warehouse/ })).toHaveAttribute(
      "aria-expanded",
      "false",
    );
    await userEvent.click(
      screen.getByRole("button", { name: "Expand Warehouse" }),
    );
    expect(onToggle).toHaveBeenCalledWith("wh");
  });

  it("names the unit of the badge: records here and below, not sublocations", () => {
    render(
      <StorageTree
        nodes={[
          {
            id: "wh",
            name: "Warehouse",
            parent_id: null,
            usage: "internal",
            short_code: null,
            items_count: 3,
            subtree_items_count: 40,
            children_count: 12,
            children: [],
          },
        ]}
        expanded={new Set()}
        onToggle={vi.fn()}
        onSelect={vi.fn()}
        canWrite={false}
        onMoveTo={vi.fn()}
        onOpenSettings={vi.fn()}
        onDragMove={vi.fn()}
        label="Storage locations"
      />,
    );

    expect(
      screen.getByTitle("40 records here and in sublocations"),
    ).toHaveTextContent("40");
  });
});

describe("StorageTree — rows a writer can act on", () => {
  const renderWritable = () => {
    const onMoveTo = vi.fn();
    const onOpenSettings = vi.fn();
    const onDragMove = vi.fn();
    const onSelect = vi.fn();
    render(
      <StorageTree
        nodes={nodes}
        expanded={new Set()}
        onToggle={vi.fn()}
        onSelect={onSelect}
        canWrite
        onMoveTo={onMoveTo}
        onOpenSettings={onOpenSettings}
        onDragMove={onDragMove}
        label="Storage locations"
      />,
    );
    return { onMoveTo, onOpenSettings, onDragMove, onSelect };
  };
  const dataTransfer = () => ({
    setData: vi.fn(),
    getData: vi.fn(),
    effectAllowed: "",
    dropEffect: "",
  });

  it("asks to move the row whose menu was opened, so the picker does not open on the wrong place", async () => {
    const { onMoveTo } = renderWritable();

    await userEvent.click(
      screen.getByRole("button", { name: "Actions for Freezer" }),
    );
    await userEvent.click(
      await screen.findByRole("button", { name: "Move to…" }),
    );

    expect(onMoveTo).toHaveBeenCalledTimes(1);
    expect(onMoveTo).toHaveBeenCalledWith("freezer");
  });

  it("lets a row's menu reach Archive and Delete, which live on the Settings tab", async () => {
    const { onOpenSettings, onSelect } = renderWritable();

    await userEvent.click(
      screen.getByRole("button", { name: "Actions for Freezer" }),
    );
    onSelect.mockClear();
    await userEvent.click(
      await screen.findByRole("button", { name: "Archive or delete…" }),
    );

    expect(onOpenSettings).toHaveBeenCalledWith("freezer");
    // The menu is a portal; its click must not bubble into the row's own
    // select, which navigates after the item did and drops the Settings tab.
    expect(onSelect).not.toHaveBeenCalled();
  });

  it("drops the highlight when the pointer leaves a row it was dragged over", () => {
    renderWritable();
    const site = screen.getByRole("treeitem", { name: /Pantry Building/ });
    const freezer = screen.getByRole("treeitem", { name: /Freezer/ });

    fireEvent.dragStart(site, { dataTransfer: dataTransfer() });
    fireEvent.dragOver(freezer, { dataTransfer: dataTransfer() });
    expect(freezer.className).toContain("ring-primary-400");

    fireEvent.dragLeave(freezer);
    expect(freezer.className).not.toContain("ring-primary-400");
  });

  it("forgets a drag that ended outside any row, so nothing stays dimmed and no move is sent", () => {
    const { onDragMove } = renderWritable();
    const site = screen.getByRole("treeitem", { name: /Pantry Building/ });
    const freezer = screen.getByRole("treeitem", { name: /Freezer/ });

    fireEvent.dragStart(site, { dataTransfer: dataTransfer() });
    fireEvent.dragOver(freezer, { dataTransfer: dataTransfer() });
    expect(site.className).toContain("opacity-50");

    fireEvent.dragEnd(site);

    expect(site.className).not.toContain("opacity-50");
    expect(freezer.className).not.toContain("ring-primary-400");
    expect(onDragMove).not.toHaveBeenCalled();
  });
});
