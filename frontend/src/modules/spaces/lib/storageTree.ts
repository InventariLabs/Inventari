import type { StorageLocationNode } from "@/types";

/**
 * The tree the Storages screen works on.
 *
 * The backend answers with a nested tree (ADR-018: a location is wherever its
 * parent puts it, at any depth), while the screens need to answer flat
 * questions about it — which locations exist, where one stands, what hangs
 * below another. These helpers were living in `StoragesPage` and were
 * imported across pages; the screen now has several parts, so they get a
 * module of their own.
 */

/** Every node of the tree, depth first — roots and everything below. */
export function flattenTree(
  nodes: StorageLocationNode[],
): StorageLocationNode[] {
  return nodes.flatMap((node) => [node, ...flattenTree(node.children ?? [])]);
}

/** The node an address names, wherever in the tree it stands. */
export function findNode(
  nodes: StorageLocationNode[],
  id: string | undefined,
): StorageLocationNode | undefined {
  if (!id) return undefined;
  return flattenTree(nodes).find((node) => node.id === id);
}

/** Every id standing below *id* — the subtree, excluding the node itself. */
export function descendantIdsOf(
  nodes: StorageLocationNode[],
  id: string,
): Set<string> {
  const node = findNode(nodes, id);
  return new Set(flattenTree(node?.children ?? []).map((child) => child.id));
}
