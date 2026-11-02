import React from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { CheckCircle, Move, Package, Trash2 } from "lucide-react";
import { extractApiError } from "@/lib/errors";
import { useCanWrite } from "@/hooks/useCanWrite";
import { useHasPermission } from "@/hooks/useHasPermission";
import { formatQuantityLocalized } from "@/lib/i18nHelpers";
import { toAmount } from "@/utils/formatters";
import { logger } from "@/utils/logger";
import type { Item } from "@/types";
import {
  useConsumeItem,
  useDeleteItem,
  useUpdateItemQuantity,
} from "@/modules/inventory/hooks/useItemMutations";

export interface ItemQuickAction {
  id: string;
  label: string;
  icon: React.ElementType;
  color: string;
  accentBorder: string;
  onClick: () => void;
  isLoading?: boolean;
  disabled?: boolean;
  danger?: boolean;
}

interface Options {
  /** Called after an action that finished with the record changed. */
  onDone: () => void;
  /** Opens the move dialog — the one thing the actions cannot do alone. */
  onMove: () => void;
  /**
   * Called instead of `onDone` once the record is gone. The sheet closes
   * either way; the record's own page has to leave, because the address it
   * sits at no longer resolves.
   */
  onDeleted?: () => void;
}

/**
 * What a reader can do to a product without opening the edit form.
 *
 * The sheet over the list had these; the product's own page had "Edit" and
 * nothing else, so the shortcut could do more than the record's own address.
 * Both read this hook, which is what keeps "consume" meaning the same thing
 * in the two places.
 *
 * Every one of them changes the record, so an account holding `items:read`
 * alone is offered none. Asking here rather than in the two consumers is what
 * keeps them from disagreeing: a sheet and a detail page that answer the same
 * question differently is how a reader learns that the answer is arbitrary.
 *
 * Delete asks a second question, because the API does: `PUT` and the quantity
 * moves are `items:write`, while `DELETE` is `items:delete` — a key built-in
 * roles grant only to the administrator. Topping up a shelf and erasing the
 * record are different rights, and the discard action used to be offered on
 * the strength of the first.
 */
export function useItemQuickActions(
  item: Item,
  { onDone, onMove, onDeleted }: Options,
) {
  const { t } = useTranslation(["labels", "common", "items", "equipment"]);
  const canWrite = useCanWrite("items");
  const canDelete = useHasPermission("items:delete");
  const isEquipmentItem = item.category?.context_tag === "equipment";
  const [isDeleteDialogOpen, setDeleteDialogOpen] = React.useState(false);

  const consumeItemMutation = useConsumeItem();
  const deleteItemMutation = useDeleteItem();
  const updateQuantityMutation = useUpdateItemQuantity();

  // One unit per press, whatever the unit measures. The action is labelled
  // "Remove 1 unit" (the sheet and the product page share this hook), and the
  // row's amount dialog is where a reader asks for more. Weighed goods used
  // to go the other way — "Remove 1 unit" on a 2 kg record took both
  // kilograms, while "Add 1 unit" beside it added exactly one.
  const consume = () =>
    consumeItemMutation.mutate(
      { itemId: item.id, quantity: 1 },
      {
        onSuccess: (updatedItem) => {
          // Only the remaining quantity decides here: this hook's discard goes
          // through confirmDelete (which deletes for real), so a consume
          // answer never carries is_deleted — the page actions' exit path,
          // whose disposal reasons discard, keeps that branch of its own.
          if ((toAmount(updatedItem.quantity) ?? 0) <= 0) {
            toast.success(t("quickAdd.finished"));
          } else {
            toast.success(
              t("items:quickActions.consumedSuccessRemaining", {
                remaining: formatQuantityLocalized(
                  t,
                  updatedItem.quantity,
                  updatedItem.uom?.symbol,
                ),
              }),
            );
          }
          onDone();
        },
        onError: (error: unknown) => {
          logger.error("Consume error:", error);
          toast.error(
            extractApiError(error, t("items:quickActions.consumeFailed")),
          );
        },
      },
    );

  const addOne = () =>
    updateQuantityMutation.mutate(
      { itemId: item.id, quantity: (Number(item.quantity) || 0) + 1 },
      {
        onSuccess: (updatedItem) => {
          toast.success(
            t("quickAdd.successTotal", {
              total: formatQuantityLocalized(
                t,
                updatedItem.quantity,
                updatedItem.uom?.symbol,
              ),
            }),
          );
          onDone();
        },
        onError: (error: unknown) => {
          logger.error("Add error:", error);
          toast.error(
            extractApiError(error, t("items:quickActions.addOneFailed")),
          );
        },
      },
    );

  /** The same operation the row's bin performs, so the reason dialog they
   *  both open describes what actually happens. This used to discard the
   *  whole quantity instead — the record stayed behind at zero while the
   *  dialog said the product was being deleted. */
  const confirmDelete = async (reason: string, notes: string) => {
    // Awaited rather than fired: the dialog closes on the way out of a delete
    // that happened, and stays put — reason and note intact — on one that did
    // not. It used to close either way, so both looked the same.
    try {
      await deleteItemMutation.mutateAsync({ itemId: item.id, reason, notes });
    } catch (error: unknown) {
      logger.error("Delete error:", error);
      throw error;
    }
    setDeleteDialogOpen(false);
    toast.success(t("items:messages.itemDeleted"));
    (onDeleted ?? onDone)();
  };

  const actions: ItemQuickAction[] = (
    canWrite
      ? [
          // Non-equipment only: consume
          !isEquipmentItem && {
            id: "consume",
            label: t("items:quickActions.consume"),
            icon: CheckCircle,
            color: "text-accent-600",
            accentBorder: "border-l-accent-500",
            onClick: consume,
            isLoading: consumeItemMutation.isPending,
            disabled: (toAmount(item.quantity) ?? 0) <= 0,
          },
          {
            id: "add_one",
            label: isEquipmentItem
              ? t("equipment:actions.checkin")
              : t("items:quickActions.addOne", { defaultValue: "+1 Unit" }),
            icon: Package,
            color: "text-primary-600",
            accentBorder: "border-l-primary-500",
            onClick: addOne,
            isLoading: updateQuantityMutation.isPending,
          },
          {
            id: "move",
            label: t("items:quickActions.move"),
            icon: Move,
            color: "text-primary-600",
            accentBorder: "border-l-blue-400",
            onClick: onMove,
          },
          // Adding to a shopping list belongs to the shopping_lists module, which
          // contributes it through the `quick_action_extra` slot. Core kept its own
          // copy of the same action, so the sheet offered it twice — and offered it
          // at all on an installation without the module.
          // Equipment actions used to sit here — "Check out" and "Decommission",
          // both of which opened the edit form. An asset is handed over and retired
          // from its own detail page, where those actions ask what they need to
          // ask; a button named after a movement that opens a form is worse than
          // no button, because it reads as though the movement was recorded.
          canDelete && {
            id: "discard",
            label: isEquipmentItem
              ? t("equipment:actions.dispose")
              : t("items:quickActions.delete"),
            icon: Trash2,
            color: "text-red-600",
            accentBorder: "border-l-red-500",
            danger: true,
            // The same dialog the list row and the edit modal open: taking
            // something off the shelf is one question, and it has one answer sheet.
            onClick: () => setDeleteDialogOpen(true),
            isLoading: deleteItemMutation.isPending,
          },
        ]
      : []
  ).filter(Boolean) as ItemQuickAction[];

  // The vocabulary above switches with the record's category: an asset is
  // checked in and disposed, a product is topped up and deleted. The switch
  // reads as arbitrary on the one screen where both kinds of record live, so
  // the note travels with the actions and says why they sound different.
  const vocabularyNote = isEquipmentItem
    ? t("items:quickActions.equipmentNote")
    : null;

  return {
    actions,
    vocabularyNote,
    deleteDialog: {
      open: isDeleteDialogOpen,
      onConfirm: confirmDelete,
      onCancel: () => setDeleteDialogOpen(false),
    },
  };
}
