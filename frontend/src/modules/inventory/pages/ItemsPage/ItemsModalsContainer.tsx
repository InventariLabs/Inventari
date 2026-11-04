import type { Item } from "@/types";
import ItemEditModal from "@/modules/inventory/components/ItemEditModal";
import ThresholdQuickSetSheet from "@/modules/inventory/components/ThresholdQuickSetSheet";
import BulkEditModal from "@/modules/inventory/components/items/BulkEditModal";
import ImportModal from "@/modules/inventory/components/items/ImportModal";

interface ItemsModalsContainerProps {
  editingItemId: string | null;
  editingAtExpiry: boolean;
  setEditingItemId: (id: string | null) => void;
  thresholdItem: Item | null;
  setThresholdItem: (item: Item | null) => void;
  showBulkEdit: boolean;
  setShowBulkEdit: (show: boolean) => void;
  selectedItemIds: string[];
  setSelectedItemIds: (ids: string[]) => void;
  showImportModal: boolean;
  setShowImportModal: (show: boolean) => void;
}

export default function ItemsModalsContainer({
  editingItemId,
  editingAtExpiry,
  setEditingItemId,
  thresholdItem,
  setThresholdItem,
  showBulkEdit,
  setShowBulkEdit,
  selectedItemIds,
  setSelectedItemIds,
  showImportModal,
  setShowImportModal,
}: ItemsModalsContainerProps) {
  return (
    <>
      {editingItemId && (
        <ItemEditModal
          itemId={editingItemId}
          openAtExpiry={editingAtExpiry}
          onClose={() => setEditingItemId(null)}
        />
      )}

      {thresholdItem && (
        <ThresholdQuickSetSheet
          item={thresholdItem}
          onClose={() => setThresholdItem(null)}
        />
      )}

      {showBulkEdit && (
        <BulkEditModal
          itemIds={selectedItemIds}
          onClose={() => setShowBulkEdit(false)}
          onSuccess={() => {
            setShowBulkEdit(false);
            setSelectedItemIds([]);
          }}
        />
      )}

      {showImportModal && (
        <ImportModal onClose={() => setShowImportModal(false)} />
      )}
    </>
  );
}
