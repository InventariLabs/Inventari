import { useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  X,
  ScanLine,
  CheckCircle2,
  AlertTriangle,
  ChevronDown,
  Link2,
} from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Sheet, SheetActions, SheetFooter } from "@/components/ui/Sheet";
import { Input } from "@/components/ui/Input";
import { Badge } from "@/components/ui/Badge";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import type {
  PickingStartResponse,
  PickingScanResponse,
  PickingItem,
} from "@/modules/recipes/types/core";
import { formatDate } from "@/utils/helpers";
import { needsProductLink } from "../utils";
import PickingItemRow from "./PickingItemRow";
import { DisambiguationOverlay } from "./PickingDisambiguation";
import type { PickingRefusal } from "../hooks/usePickingSession";
import type { TFunction } from "i18next";

interface Props {
  phase: "active" | "disambiguation" | "opened_suggestion" | "fefo_mismatch";
  session: PickingStartResponse;
  items: PickingItem[];
  /** Per ingredient, the last scan the server refused to act on. */
  refusals?: Record<string, PickingRefusal>;
  scanResult?: PickingScanResponse;
  recipeName: string;
  servings: number;
  isLoading: boolean;
  error: string | null;
  onScan: (barcode: string) => void;
  onTapIngredient: (item: PickingItem) => void;
  onUndoIngredient: (item: PickingItem) => void;
  recipeId: string;
  /** Re-reads the session after an ingredient was linked in place. */
  onLinked: () => void;
  onComplete: () => void;
  onCancel: () => void;
  onClose: () => void;
  resolveDisambiguation: (itemId: string) => void;
  dismissOpenedSuggestion: () => void;
}

/**
 * The sheet's title row: the recipe, the resumed badge when an open session
 * came back, and how far the checklist is. Extracted from the phase component
 * to keep its branch count under the lint cap.
 */
function SheetHeaderRow({
  recipeName,
  session,
  servings,
  pickedCount,
  trackableCount,
  onClose,
  t,
}: {
  recipeName: string;
  session: PickingStartResponse;
  servings: number;
  pickedCount: number;
  trackableCount: number;
  onClose: () => void;
  t: TFunction;
}) {
  return (
    <div className="flex items-center justify-between px-5 py-3.5 border-b border-border shrink-0">
      <div className="min-w-0">
        <div className="flex items-center gap-2 min-w-0">
          <p className="text-base font-semibold text-on truncate">
            {t("picking.title", {
              recipe: session?.recipe_name ?? recipeName,
            })}
          </p>
          {/* An open session comes back with its own servings and its own
              half-ticked list; the toast that said so is gone in seconds, and
              the sheet is read for as long as the cooking takes. */}
          {session?.resumed && (
            <Badge variant="warning" className="shrink-0">
              {t("picking.resumed_badge")}
            </Badge>
          )}
        </div>
        <p className="text-xs text-on-secondary mt-0.5">
          {pickedCount}/{trackableCount} ·{" "}
          {t("picking.subtitle", { count: session?.servings ?? servings })}
        </p>
      </div>
      <Button
        variant="ghost"
        size="icon"
        onClick={onClose}
        className="text-on-muted hover:text-on-secondary shrink-0 ml-2"
        aria-label={t("common:a11y.close")}
      >
        <X size={16} />
      </Button>
    </div>
  );
}

export default function PickingActivePhase({
  phase,
  session,
  items,
  refusals = {},
  scanResult,
  recipeName,
  servings,
  isLoading,
  error,
  onScan,
  onTapIngredient,
  onUndoIngredient,
  recipeId,
  onLinked,
  onComplete,
  onCancel,
  onClose,
  resolveDisambiguation,
  dismissOpenedSuggestion,
}: Props) {
  const { t } = useTranslation(["recipes", "common"]);
  const barcodeRef = useRef<HTMLInputElement>(null);
  const [showCompleteConfirm, setShowCompleteConfirm] = useState(false);
  const [barcodeValue, setBarcodeValue] = useState("");
  const [skippedExpanded, setSkippedExpanded] = useState(false);

  const trackableItems = items.filter((i) => i.status !== "skipped");
  const skippedItems = items.filter((i) => i.status === "skipped");
  const pickedCount = items.filter((i) => i.status === "picked").length;
  // One notice for the whole list: the fact is collective, and the way out of
  // it costs the session, so it is stated once instead of in every row.
  const unlinkedCount = trackableItems.filter(needsProductLink).length;
  // A recipe none of whose ingredients is on the shelf used to be refused a
  // session at all, on a guess made from `template_id`. The session now
  // starts and the sheet says the true reason it is empty.
  const nothingInStock =
    trackableItems.length > 0 &&
    trackableItems.every((i) => i.recommended_item_id == null);
  const noticeText = nothingInStock
    ? t("picking.nothing_in_stock_notice")
    : unlinkedCount > 0
      ? t("picking.unlinked_notice", {
          count: unlinkedCount,
          total: trackableItems.length,
        })
      : null;

  // A session that picked everything has nothing left to skip, and was still
  // being warned that the remainder would be marked as skipped — over 1 of 1.
  const allPicked =
    trackableItems.length > 0 && pickedCount === trackableItems.length;
  const completeConfirmMessage =
    pickedCount === 0
      ? t("picking.completeZeroConfirmMessage")
      : allPicked
        ? t("picking.completeAllConfirmMessage")
        : t("picking.completeConfirmMessage", {
            picked: pickedCount,
            total: trackableItems.length,
          });

  const handleBarcodeSubmit = () => {
    const val = barcodeValue.trim();
    if (val) {
      onScan(val);
      setBarcodeValue("");
    }
  };

  return (
    <>
      <Sheet
        open
        onClose={onClose}
        zIndex="modal"
        maxWidth="xl"
        fullBleedOnMobile
        aria-label={t("picking.title", {
          recipe: session?.recipe_name ?? recipeName,
        })}
      >
        <SheetHeaderRow
          recipeName={recipeName}
          session={session}
          servings={servings}
          pickedCount={pickedCount}
          trackableCount={trackableItems.length}
          onClose={onClose}
          t={t}
        />

        {/* Barcode input */}
        {phase === "active" && (
          <div className="px-5 py-3 border-b border-border shrink-0">
            <div className="flex gap-2">
              <div className="flex-1">
                <Input
                  ref={barcodeRef}
                  aria-label={t("picking.scan_prompt")}
                  value={barcodeValue}
                  onChange={(e) => setBarcodeValue(e.target.value)}
                  placeholder={t("picking.scan_prompt")}
                  leftIcon={<ScanLine size={16} className="text-on-muted" />}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") handleBarcodeSubmit();
                  }}
                  autoFocus
                />
              </div>
            </div>
          </div>
        )}

        {/* Error */}
        {error && (
          <div className="px-5 py-2.5 bg-red-50 text-sm text-on-danger font-medium shrink-0 border-b border-red-100">
            {error}
          </div>
        )}

        {/* Ingredients list */}
        <div className="flex-1 overflow-y-auto divide-y divide-border">
          {/* Nothing here can reach stock — said once, above the list */}
          {noticeText && (
            <div className="flex items-start gap-2.5 px-5 py-3 border-b border-amber-200 bg-amber-50">
              <Link2 size={15} className="text-on-warning mt-0.5 shrink-0" />
              <p className="min-w-0 text-xs text-on-warning leading-relaxed">
                {noticeText}
              </p>
            </div>
          )}

          {trackableItems.map((item) => (
            <PickingItemRow
              key={item.ingredient_id}
              item={item}
              refusal={refusals[item.ingredient_id]}
              onTap={onTapIngredient}
              onUndo={onUndoIngredient}
              recipeId={recipeId}
              onLinked={onLinked}
            />
          ))}

          {trackableItems.length === 0 && (
            <div className="p-8 text-center text-sm text-on-muted">
              {t("picking.complete_confirm")}
            </div>
          )}

          {/* Collapsed spices / auto-skipped section */}
          {skippedItems.length > 0 && (
            <div>
              <Button
                size="content"
                variant="ghost"
                onClick={() => setSkippedExpanded((v) => !v)}
                // `active:scale-100` on purpose: this is a full-width
                // row in a list, and shrinking the whole strip by 2% reads as a
                // glitch rather than a press. The `active:` background is the
                // feedback here, as it is for the item rows above it.
                className="w-full justify-between px-5 py-2.5 text-xs text-on-secondary hover:bg-surface active:bg-surface rounded-none active:scale-100"
              >
                <span>
                  {t("picking.spices_section", { count: skippedItems.length })}
                </span>
                <ChevronDown
                  size={16}
                  className={`transition-transform ${skippedExpanded ? "rotate-180" : ""}`}
                />
              </Button>
              {skippedExpanded &&
                skippedItems.map((item) => (
                  <PickingItemRow
                    key={item.ingredient_id}
                    item={item}
                    refusal={refusals[item.ingredient_id]}
                    onTap={onTapIngredient}
                    onUndo={onUndoIngredient}
                    recipeId={recipeId}
                    onLinked={onLinked}
                  />
                ))}
            </div>
          )}
        </div>

        {/* Overlays */}
        {phase !== "active" && (
          <div className="absolute inset-0 bg-surface-card/[0.97] flex flex-col z-10 animate-in fade-in zoom-in-95 duration-200 motion-reduce:animate-none">
            {phase === "disambiguation" && scanResult && (
              <DisambiguationOverlay
                scanResult={scanResult}
                onChoose={resolveDisambiguation}
                onCancel={dismissOpenedSuggestion}
              />
            )}

            {/* Opened suggestion overlay */}
            {phase === "opened_suggestion" && scanResult?.opened_suggestion && (
              <div className="flex flex-col h-full p-5">
                <div className="flex-1">
                  <p className="text-base font-semibold text-on mb-1">
                    {t("picking.opened_suggestion.title")}
                  </p>
                  <p className="text-sm text-on-secondary">
                    {t("picking.opened_suggestion.description", {
                      item: scanResult.ingredient_name ?? "",
                      quantity: scanResult.opened_suggestion.opened_quantity,
                      uom: scanResult.opened_suggestion.opened_uom ?? "",
                      location:
                        scanResult.opened_suggestion.opened_location ?? "",
                    })}
                  </p>
                </div>
                <SheetActions className="shrink-0 mt-5">
                  <Button
                    variant="outline"
                    onClick={() => dismissOpenedSuggestion()}
                  >
                    {t("picking.opened_suggestion.ignore")}
                  </Button>
                  <Button
                    onClick={() =>
                      resolveDisambiguation(
                        scanResult.opened_suggestion!.opened_item_id,
                      )
                    }
                  >
                    {t("picking.opened_suggestion.use")}
                  </Button>
                </SheetActions>
              </div>
            )}

            {/* FEFO mismatch overlay */}
            {phase === "fefo_mismatch" && scanResult && (
              <div className="flex flex-col h-full p-5">
                <div className="flex-1">
                  <div className="flex items-center gap-2 mb-1">
                    <AlertTriangle
                      size={18}
                      className="text-amber-500 shrink-0"
                    />
                    <p className="text-base font-semibold text-on">
                      {t("picking.fefo_mismatch.title")}
                    </p>
                  </div>
                  <p className="text-sm text-on-secondary">
                    {t("picking.fefo_mismatch.description", {
                      ingredient: scanResult.ingredient_name ?? "",
                      date: scanResult.fefo_recommended_expiry_date
                        ? formatDate(scanResult.fefo_recommended_expiry_date)
                        : "",
                    })}
                  </p>
                </div>
                <SheetActions className="shrink-0 mt-5">
                  <Button
                    variant="outline"
                    onClick={() =>
                      resolveDisambiguation(scanResult.fefo_scanned_item_id!)
                    }
                  >
                    {t("picking.fefo_mismatch.use_scanned")}
                  </Button>
                  <Button
                    variant="primary"
                    onClick={() =>
                      resolveDisambiguation(
                        scanResult.fefo_recommended_item_id!,
                      )
                    }
                  >
                    {t("picking.fefo_mismatch.use_recommended", {
                      date: scanResult.fefo_recommended_expiry_date
                        ? formatDate(scanResult.fefo_recommended_expiry_date)
                        : "",
                    })}
                  </Button>
                </SheetActions>
              </div>
            )}
          </div>
        )}

        {/* `bg-surface` (not `-card`) keeps the recessed footer tint the
            original `bg-surface/50` gave it — and inverts correctly in dark. */}
        <SheetFooter className="bg-surface">
          <SheetActions>
            <Button
              variant="outline"
              onClick={onCancel}
              isLoading={isLoading}
              className="text-on-danger border-red-200 hover:bg-red-50"
            >
              {t("picking.cancel")}
            </Button>
            <Button
              onClick={() => setShowCompleteConfirm(true)}
              isLoading={isLoading}
              leftIcon={<CheckCircle2 size={16} />}
              className="gap-1"
            >
              {t("picking.complete")}
            </Button>
          </SheetActions>
        </SheetFooter>
      </Sheet>
      <ConfirmDialog
        open={showCompleteConfirm}
        onCancel={() => setShowCompleteConfirm(false)}
        onConfirm={() => {
          setShowCompleteConfirm(false);
          onComplete();
        }}
        title={
          pickedCount === 0
            ? t("picking.completeZeroConfirmTitle")
            : t("picking.completeConfirmTitle")
        }
        message={completeConfirmMessage}
        confirmLabel={t("picking.complete")}
        cancelLabel={t("common:form.cancel")}
        variant={pickedCount === 0 ? "warning" : "default"}
      />
    </>
  );
}
