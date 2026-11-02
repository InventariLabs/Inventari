import { memo } from "react";
import { useTranslation } from "react-i18next";
import { Minus, Plus, RotateCcw, Save } from "lucide-react";
import type { Item } from "@/types";
import type {
  StockTakeCount,
  StockTakeItem,
} from "@/modules/stock_takes/types/stock-takes";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { unitLabel } from "@/lib/i18nHelpers";
import { cn } from "@/lib/utils";
import { ReasonCodeField } from "@/modules/shared/components/ReasonCodeField";
import {
  DISCREPANCY_REASON_CODES,
  type StockTakeDiscrepancyCode,
} from "@/modules/stock_takes/discrepancyCodes";
import { recordMarks, type Twin } from "@/modules/stock_takes/recordMarks";
import StockTakeItemCardHeader from "./StockTakeItemCardHeader";
import StockTakeItemFigures from "./StockTakeItemFigures";

interface Props {
  itemId: string;
  item: Item | undefined;
  stockTakeItem: StockTakeItem | undefined;
  /** What the box holds, as typed — see `useCountingDrafts`. */
  counted: string;
  savedCount: number | null;
  discrepancy: "missing" | "surplus" | null;
  twin?: Twin | null;
  isSaved: boolean;
  isUnsaved: boolean;
  awaitingRecount: boolean;
  counts: StockTakeCount[];
  onRequestRecount: (itemId: string) => void;
  isUpdatePending: boolean;
  isInProgress: boolean;
  blindMode: boolean;
  note: string;
  reasonCode: StockTakeDiscrepancyCode | "";
  reasonNote: string;
  showReasonErrors: boolean;
  /** Whether completing refuses a difference with no reason (a tolerance is set). */
  reasonRequired?: boolean;
  onReasonChange: (
    itemId: string,
    reason: { code: StockTakeDiscrepancyCode | ""; note: string },
  ) => void;
  onNoteChange: (itemId: string, value: string) => void;
  onQuantityChange: (itemId: string, text: string) => void;
  onQuantityStep: (itemId: string, delta: number) => void;
  onSave: (itemId: string) => void;
}

const StockTakeItemCard = memo(function StockTakeItemCard({
  itemId,
  item,
  stockTakeItem,
  counted,
  savedCount,
  discrepancy,
  twin,
  isSaved,
  isUnsaved,
  awaitingRecount,
  counts,
  onRequestRecount,
  isUpdatePending,
  isInProgress,
  blindMode,
  note,
  reasonCode,
  reasonNote,
  showReasonErrors,
  reasonRequired = true,
  onReasonChange,
  onNoteChange,
  onQuantityChange,
  onQuantityStep,
  onSave,
}: Props) {
  const { t } = useTranslation(["stock_takes"]);
  // Sixty-four of these buttons on a page of thirty-two products, and every one
  // of them announced itself as nothing at all. The name has to say which shelf
  // line it belongs to, or the reader counts blind. Two records of one product
  // on one shelf are told apart by their batch and expiry, in the name too.
  const productName = [
    item?.name ?? stockTakeItem?.item_name ?? itemId,
    ...recordMarks(t, item, stockTakeItem, twin),
  ].join(", ");
  // The two step buttons say what a step is: "one more" is one kilogram on a
  // weighed row, not one banana — and in the reader's word for it ("szt."),
  // not the record's ("pcs"), which is what a screen reader used to announce.
  // `unitLabel` is the one place that decides the word, as
  // `StockTakeItemFigures` beside it does for the figures.
  const unit = unitLabel(t, stockTakeItem?.uom_symbol);
  return (
    <div
      data-testid="stock-take-item-card"
      data-item-id={itemId}
      className={`bg-surface-card rounded-xl p-4 border shadow-sm ${discrepancy ? "border-amber-300" : ""}`}
    >
      <div className="flex flex-col gap-3 xs:flex-row xs:items-start xs:justify-between">
        <div className="flex-1">
          <StockTakeItemCardHeader
            itemId={itemId}
            item={item}
            stockTakeItem={stockTakeItem}
            savedCount={savedCount}
            discrepancy={discrepancy}
            twin={twin}
            isUnsaved={isUnsaved}
            awaitingRecount={awaitingRecount}
          />
          {stockTakeItem &&
            stockTakeItem.system_quantity !== null &&
            !blindMode && (
              <StockTakeItemFigures
                stockTakeItem={stockTakeItem}
                savedCount={savedCount}
                discrepancy={discrepancy}
              />
            )}
        </div>

        {isInProgress && (
          // below the xs breakpoint (475 px) the controls move to
          // their own full-width row under the product name — at 390 px the
          // previous single-row layout pushed "+" and the save button past
          // the right edge of the card with no horizontal scroll. 44 px
          // (h-11) touch targets for the main counting controls.
          <div className="flex items-center gap-2 w-full xs:w-auto">
            <Button
              size="icon"
              variant="outline"
              className="shrink-0"
              onClick={() => onQuantityStep(itemId, -1)}
              aria-label={
                unit
                  ? t("item.decreaseCountInUnit", { unit, name: productName })
                  : t("item.decreaseCount", { name: productName })
              }
            >
              <Minus size={18} />
            </Button>
            {/* Text, not a number: a number field hands back an empty value
                for the "2." in the middle of "2.1", and the box then rewrites
                itself over the dot. What is typed stays typed;
                `countingQuantity` reads the number out of it, and the step of
                the row's own unit decides what may be saved. */}
            <Input
              wrapperClassName="flex-1 min-w-0 xs:flex-none xs:w-16"
              type="text"
              inputMode="decimal"
              value={counted}
              onChange={(e) => onQuantityChange(itemId, e.target.value)}
              className="h-11 text-center"
              aria-label={t("item.countFor", { name: productName })}
            />
            <Button
              size="icon"
              variant="outline"
              className="shrink-0"
              onClick={() => onQuantityStep(itemId, 1)}
              aria-label={
                unit
                  ? t("item.increaseCountInUnit", { unit, name: productName })
                  : t("item.increaseCount", { name: productName })
              }
            >
              <Plus size={18} />
            </Button>
            {discrepancy && !awaitingRecount && (
              // The first answer to a difference nobody expected is to count
              // it again, not to approve it. The row keeps its number and
              // will not post until somebody has looked a second time.
              <Button
                size="icon"
                variant="outline"
                className="shrink-0"
                onClick={() => onRequestRecount(itemId)}
                aria-label={t("item.countAgain", { name: productName })}
              >
                <RotateCcw size={18} />
              </Button>
            )}
            <Button
              size="icon"
              className={cn(
                "shrink-0",
                isSaved
                  ? "bg-success-600 hover:bg-success-700 text-white"
                  : "bg-primary-700 dark:bg-primary-800 hover:bg-primary-800 dark:hover:bg-primary-900 text-white",
              )}
              onClick={() => onSave(itemId)}
              disabled={isSaved || isUpdatePending}
              aria-label={t("item.saveCount", { name: productName })}
            >
              <Save size={18} />
            </Button>
          </div>
        )}
      </div>

      {counts.length > 1 && (
        // Both numbers, with the names behind them. Two people arriving at
        // the same figure is what makes the correction believable, and a
        // disagreement between them is worth seeing rather than averaging.
        <p className="mt-2 text-xs text-on-secondary tabular-nums">
          {counts
            .map((pass) =>
              t("item.countedPass", {
                sequence: pass.sequence,
                quantity: pass.quantity,
                name: pass.counted_by_name ?? t("item.someone"),
              }),
            )
            .join(" · ")}
        </p>
      )}

      {isInProgress && (
        <div className="mt-3">
          <Input
            type="text"
            value={note}
            onChange={(e) => onNoteChange(itemId, e.target.value)}
            placeholder={t("item.notePlaceholder")}
            aria-label={t("item.noteFor", { name: productName })}
          />
        </div>
      )}

      {/* Only where there is a difference to explain, and only once the
          count has been recorded: the flag is the server's answer, so the
          field cannot appear before the number is in and cannot tell a blind
          counter that their number was wrong before they have committed it. */}
      {isInProgress && discrepancy && (
        <div className="mt-3">
          <ReasonCodeField
            testId="discrepancy-reason"
            label={t("reasons.discrepancy.label")}
            codes={DISCREPANCY_REASON_CODES}
            labelFor={(code) => t(`reasons.discrepancy.codes.${code}`)}
            code={reasonCode}
            onCodeChange={(code) =>
              onReasonChange(itemId, { code, note: reasonNote })
            }
            note={reasonNote}
            onNoteChange={(value) =>
              onReasonChange(itemId, { code: reasonCode, note: value })
            }
            showErrors={showReasonErrors}
            required={reasonRequired}
          />
        </div>
      )}
    </div>
  );
});

export default StockTakeItemCard;
