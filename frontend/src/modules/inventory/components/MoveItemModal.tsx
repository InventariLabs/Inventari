import { useState } from "react";
import { useTranslation } from "react-i18next";
import { X, Loader2, Move } from "lucide-react";
import { toast } from "sonner";
import { extractApiError } from "@/lib/errors";
import { useMoveItem } from "@/modules/inventory/hooks/useItemMutations";
import { Button } from "@/components/ui/Button";
import { LocationCombobox } from "@/module-sdk";
import { Sheet, SheetActions, SheetFooter } from "@/components/ui/Sheet";
import type { Item } from "@/types";

interface MoveItemModalProps {
  item: Item;
  onClose: () => void;
  onSuccess: () => void;
}

export function MoveItemModal({
  item,
  onClose,
  onSuccess,
}: MoveItemModalProps) {
  const { t } = useTranslation(["common", "items", "labels"]);
  const moveItemMutation = useMoveItem();
  const [selectedStorageId, setSelectedStorageId] = useState(item.location_id);

  const moveMutation = {
    mutate: (storageId: string) =>
      moveItemMutation.mutate(
        { itemId: item.id, storageLocationId: storageId },
        {
          onSuccess: () => {
            toast.success(t("items:quickActions.moveSuccess"));
            onSuccess();
          },
          onError: (error: unknown) => {
            toast.error(extractApiError(error, "Failed to move item"));
          },
        },
      ),
    isPending: moveItemMutation.isPending,
  };

  return (
    <Sheet
      open
      onClose={onClose}
      aria-label={t("items:quickActions.move", { defaultValue: "Move item" })}
      backdropOpacity={60}
    >
      <div className="bg-primary-50/50 p-6 border-b flex items-center justify-between">
        <h2 className="text-xl font-semibold text-on flex items-center gap-2">
          <Move size={24} className="text-primary-700" />
          {t("items:quickActions.move")}
        </h2>
        <Button
          variant="ghost"
          size="icon"
          onClick={onClose}
          aria-label={t("common:actions.close")}
        >
          <X size={20} />
        </Button>
      </div>

      <div className="p-6 space-y-4 flex-1 overflow-y-auto">
        <p className="text-sm text-on-secondary">
          {t("items:quickActions.movePrompt", {
            name: item.name,
            defaultValue: `Choose a new location for ${item.name}:`,
          })}
        </p>

        {/* One question, one answer: the destinations are the set the product
            form's picker offers — a stock flow's, never a module's place —
            and the place the item stands in is named by its id, so the
            sheet never opens on a value the list cannot name. */}
        <LocationCombobox
          scope={{ purpose: "stock" }}
          value={selectedStorageId}
          onChange={setSelectedStorageId}
          placeholder={t("items:selectStorage", {
            defaultValue: "Select storage",
          })}
          searchPlaceholder={t("common:search", { defaultValue: "Search..." })}
          emptyMessage={t("common:noResults")}
          label={t("items:itemStorage")}
        />
      </div>

      <SheetFooter>
        <SheetActions>
          <Button variant="outline" onClick={onClose}>
            {t("actions.cancel")}
          </Button>
          <Button
            onClick={() =>
              selectedStorageId && moveMutation.mutate(selectedStorageId)
            }
            disabled={
              moveMutation.isPending ||
              !selectedStorageId ||
              selectedStorageId === item.location_id
            }
          >
            {moveMutation.isPending ? (
              <Loader2 size={20} className="animate-spin" />
            ) : (
              <Move size={20} />
            )}
            {t("items:quickActions.move")}
          </Button>
        </SheetActions>
      </SheetFooter>
    </Sheet>
  );
}
