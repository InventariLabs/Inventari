import { useState } from "react";
import { TypedSlot } from "@/components/Slot";
import { MoveItemModal, QuickActionSheet } from "@/modules/inventory/moduleApi";
import type { Item } from "@/types";

interface StorageItemModalsProps {
  editingItemId: string | null;
  setEditingItemId: (id: string | null) => void;
  actionItem: Item | null;
  setActionItem: (item: Item | null) => void;
}

/**
 * The windows a product row opens on a location's page: edit, quick actions,
 * move. A location's own editor is not one of them any more — its settings
 * live on the page beside the tree.
 *
 * "Move" over a product opens the move dialog, the same one the items list
 * opens for the same action; this dialog does not open the product form, so the
 * reader is handed the move instead of product details.
 */
export default function StorageItemModals({
  editingItemId,
  setEditingItemId,
  actionItem,
  setActionItem,
}: StorageItemModalsProps) {
  const [movingItem, setMovingItem] = useState<Item | null>(null);

  return (
    <>
      {editingItemId && (
        <TypedSlot
          name="storage_item_edit_modal"
          data={{
            itemId: editingItemId,
            onClose: () => setEditingItemId(null),
          }}
        />
      )}

      {actionItem && (
        <QuickActionSheet
          item={actionItem}
          onClose={() => setActionItem(null)}
          onViewDetails={() => {
            setEditingItemId(actionItem.id);
            setActionItem(null);
          }}
          onMove={() => {
            setMovingItem(actionItem);
            setActionItem(null);
          }}
        />
      )}

      {movingItem && (
        <MoveItemModal
          item={movingItem}
          onClose={() => setMovingItem(null)}
          onSuccess={() => setMovingItem(null)}
        />
      )}
    </>
  );
}
