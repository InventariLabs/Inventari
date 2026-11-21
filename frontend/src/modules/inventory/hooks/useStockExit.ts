import { useMemo } from "react";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { extractApiError } from "@/lib/errors";
import {
  useConsumeItem,
  useDiscardItem,
} from "@/modules/inventory/hooks/useItemMutations";
import { toAmount } from "@/utils/formatters";
import { formatQuantityLocalized } from "@/lib/i18nHelpers";
import {
  isDisposalReason,
  reasonLabelKey,
  type StockReason,
} from "@/modules/inventory/constants/stockReasons";
import type { Item } from "@/types";

/**
 * Taking stock off a record, with the reason the reader picked.
 *
 * Every host of the amount dialog (the product list, the product page, the
 * scan sheet) sends its answer through this one hook, so a disposal reason
 * reaches the discard endpoint and a use reaches consume, and the toast that
 * follows says back what the reader chose.
 */
export function useStockExit() {
  const { t } = useTranslation(["items", "labels", "common"]);
  const navigate = useNavigate();
  const consumeItemMutation = useConsumeItem();
  const discardItemMutation = useDiscardItem();
  return useMemo(() => {
    // The reader picked a reason; the confirmation has to say it back —
    // "used up" after picking "Expired" reports a different event than the
    // one that just happened.
    const finishedMessage = (reason: string) =>
      reason === "USED"
        ? t("labels:quickAdd.finished")
        : t("items:quickActions.finishedWithReason", {
            reason: t(reasonLabelKey(reason as StockReason)),
          });
    // The dialog lets the reader remove any amount, so the confirmation names
    // the amount that was asked for, not a fixed single unit.
    const consumedMessage = (
      reason: string,
      updatedItem: Item,
      quantity: number,
    ) =>
      reason === "USED"
        ? t("items:quickActions.consumedSuccessRemaining", {
            removed: formatQuantityLocalized(
              t,
              quantity,
              updatedItem.uom?.symbol,
              updatedItem.uom?.rounding,
            ),
            remaining: formatQuantityLocalized(
              t,
              updatedItem.quantity,
              updatedItem.uom?.symbol,
              updatedItem.uom?.rounding,
            ),
          })
        : t("items:quickActions.consumedSuccessWithReason", {
            reason: t(reasonLabelKey(reason as StockReason)),
            removed: formatQuantityLocalized(
              t,
              quantity,
              updatedItem.uom?.symbol,
              updatedItem.uom?.rounding,
            ),
            remaining: formatQuantityLocalized(
              t,
              updatedItem.quantity,
              updatedItem.uom?.symbol,
              updatedItem.uom?.rounding,
            ),
          });
    // Consuming the last unit files the record under the virtual Consumed
    // location, so it vanishes from this list — say so, and hand the way
    // back: the detail page still opens for a record with nothing left.
    const usedUpToastOptions = (itemId: string) => ({
      description: t("items:quickActions.recordLeftList"),
      action: {
        label: t("items:quickActions.openRecord"),
        onClick: () => navigate(`/inventory/items/${itemId}`),
      },
    });
    // Thrown out is not used up: a disposal reason goes to the discard
    // endpoint, whose action the ledger, the journal and the waste report
    // can tell apart from a use. Routed through consume, every bin read as
    // 0.00 wasted and the journal said "Use" beside the word "DISPOSED".
    const stockExitMutation = (reason: string) =>
      isDisposalReason(reason) ? discardItemMutation : consumeItemMutation;
    return {
      mutate: (itemId: string, quantity = 1, reason = "USED", notes?: string) =>
        stockExitMutation(reason).mutate(
          { itemId, quantity, reason, notes },
          {
            onSuccess: (updatedItem) => {
              if (updatedItem.is_deleted) {
                toast.success(finishedMessage(reason));
              } else if ((toAmount(updatedItem.quantity) ?? 0) <= 0) {
                toast.success(
                  finishedMessage(reason),
                  usedUpToastOptions(itemId),
                );
              } else {
                toast.success(consumedMessage(reason, updatedItem, quantity));
              }
            },
            onError: (error: unknown) => {
              toast.error(
                extractApiError(
                  error,
                  isDisposalReason(reason)
                    ? t("items:quickActions.discardFailed")
                    : t("items:quickActions.consumeFailed"),
                ),
              );
            },
          },
        ),
      mutateAsync: async (
        itemId: string,
        quantity = 1,
        reason = "USED",
        notes?: string,
      ) => {
        const updatedItem = await stockExitMutation(reason).mutateAsync({
          itemId,
          quantity,
          reason,
          notes,
        });
        if (updatedItem.is_deleted) {
          toast.success(finishedMessage(reason));
        } else if ((toAmount(updatedItem.quantity) ?? 0) <= 0) {
          toast.success(finishedMessage(reason), usedUpToastOptions(itemId));
        } else {
          toast.success(consumedMessage(reason, updatedItem, quantity));
        }
      },
      isPending: consumeItemMutation.isPending || discardItemMutation.isPending,
      variables: consumeItemMutation.variables ?? discardItemMutation.variables,
    };
  }, [consumeItemMutation, discardItemMutation, t, navigate]);
}
