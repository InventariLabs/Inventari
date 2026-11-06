/**
 * What the inventory module publishes to the modules that depend on it.
 *
 * `check:boundaries` counts every import of a module's internals as an edge;
 * this file is the one it lets through. A name is added here when a second
 * module needs it, and removing or renaming one is a breaking change for
 * them — the same rule the backend's `items_api` follows.
 */
// The category form, which equipment opens for its own category kind.
export { CategoryFormModal } from "./components/CategoryFormModal";
// What a location's contents list opens on one item: its actions and the move.
export { default as QuickActionSheet } from "./components/QuickActionSheet";
export { MoveItemModal } from "./components/MoveItemModal";
// Delete asks for a reason here as it does on the items list.
export { DeleteReasonDialog } from "./components/DeleteReasonDialog";
// The item search and create a count uses for an item it did not expect.
export { useItemSearch } from "./hooks/useItems";
export { useCreateItem } from "./hooks/useItemMutations";
