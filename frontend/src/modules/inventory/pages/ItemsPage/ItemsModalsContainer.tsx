import { lazy, Suspense } from "react";
import type { Item } from "@/types";
import { useSearchParams } from "react-router-dom";
import ItemEditModal from "@/modules/inventory/components/ItemEditModal";
import ThresholdQuickSetSheet from "@/modules/inventory/components/ThresholdQuickSetSheet";
import BulkEditModal from "@/modules/inventory/components/items/BulkEditModal";

// Importing a file is a desk task, opened on request: its own chunk keeps the
// import dialog (file upload, column mapping, the move from Grocy) off the
// product list a phone downloads.
const ImportModal = lazy(
  () => import("@/modules/inventory/components/items/ImportModal"),
);

interface ItemsModalsContainerProps {
  editingItemId: string | null;
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
  const [searchParams] = useSearchParams();
  return (
    <>
      {editingItemId && (
        <ItemEditModal
          itemId={editingItemId}
          openAtExpiry={searchParams.get("at") === "expiry"}
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
        <Suspense fallback={null}>
          <ImportModal onClose={() => setShowImportModal(false)} />
        </Suspense>
      )}
    </>
  );
}
