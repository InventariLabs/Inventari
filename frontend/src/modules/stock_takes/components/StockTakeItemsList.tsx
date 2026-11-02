import { useTranslation } from "react-i18next";
import { Package } from "lucide-react";
import type { Item } from "@/types";
import { toAmount } from "@/utils/formatters";
import type { StockTakeItem } from "@/modules/stock_takes/types/stock-takes";
import type { StockTakeDiscrepancyCode } from "@/modules/stock_takes/discrepancyCodes";
import StockTakeItemCard from "./StockTakeItemCard";
import { recordMarks, type Twin } from "@/modules/stock_takes/recordMarks";

interface Props {
  allItemIds: string[];
  showDiscrepancies: boolean;
  countedQuantities: Record<string, string>;
  notes: Record<string, string>;
  reasons: Record<
    string,
    { code: StockTakeDiscrepancyCode | ""; note: string }
  >;
  triedToSave: Record<string, boolean>;
  reasonRequired: boolean;
  stockTakeStatus: string;
  blindMode: boolean;
  isUpdatePending: boolean;
  locationLevelFilter: string;
  /** The shelf being counted: only its rows are shown. */
  shelfId: string | null;
  getItemById: (id: string) => Item | undefined;
  getStockTakeItem: (id: string) => StockTakeItem | undefined;
  hasDiscrepancy: (id: string) => boolean;
  getDiscrepancyType: (id: string) => "missing" | "surplus" | null;
  isUnsaved: (id: string) => boolean;
  onNoteChange: (itemId: string, value: string) => void;
  onReasonChange: (
    itemId: string,
    reason: { code: StockTakeDiscrepancyCode | ""; note: string },
  ) => void;
  onQuantityChange: (itemId: string, text: string) => void;
  onQuantityStep: (itemId: string, delta: number) => void;
  onSave: (itemId: string) => void;
  onRequestRecount: (itemId: string) => void;
}

export default function StockTakeItemsList({
  allItemIds,
  showDiscrepancies,
  countedQuantities,
  notes,
  reasons,
  triedToSave,
  reasonRequired,
  stockTakeStatus,
  blindMode,
  isUpdatePending,
  locationLevelFilter,
  shelfId,
  getItemById,
  getStockTakeItem,
  hasDiscrepancy,
  getDiscrepancyType,
  isUnsaved,
  onNoteChange,
  onReasonChange,
  onQuantityChange,
  onQuantityStep,
  onSave,
  onRequestRecount,
}: Props) {
  const { t } = useTranslation(["stock_takes"]);
  const filteredIds = showDiscrepancies
    ? allItemIds.filter(hasDiscrepancy)
    : allItemIds;

  const addedAt = (itemId: string) => getItemById(itemId)?.created_at ?? "";

  // walk the rack in one pass — items with a location code come
  // first (sorted by code, then by name); uncoded items last by name.
  const orderedIds = [...filteredIds].sort((a, b) => {
    const locA = getStockTakeItem(a)?.shelf_location ?? "";
    const locB = getStockTakeItem(b)?.shelf_location ?? "";
    const nameA = getItemById(a)?.name ?? getStockTakeItem(a)?.item_name ?? "";
    const nameB = getItemById(b)?.name ?? getStockTakeItem(b)?.item_name ?? "";
    const keyA = `${locA === "" ? "\uffff" : locA} ${nameA}`;
    const keyB = `${locB === "" ? "\uffff" : locB} ${nameB}`;
    // Records of one product on one shelf in the order they came in, the
    // order their numbers below follow.
    return keyA.localeCompare(keyB) || addedAt(a).localeCompare(addedAt(b));
  });

  // Receipts into one place leave one record each, and nothing but where
  // they came from tells them apart: the rows of one product, batch and
  // place are numbered in the order they were added and carry that moment,
  // so neither the eye nor a screen reader meets the same row twice. Grouped
  // over the whole count, not the rows a filter leaves, so a row keeps its
  // number when the discrepancy filter hides its siblings.
  const twinOf = new Map<string, Twin>();
  const twinGroups = new Map<string, string[]>();
  for (const itemId of allItemIds) {
    const key = [
      getStockTakeItem(itemId)?.location_id,
      getItemById(itemId)?.name ?? getStockTakeItem(itemId)?.item_name,
      ...recordMarks(t, getItemById(itemId), getStockTakeItem(itemId)),
    ].join("|");
    twinGroups.set(key, [...(twinGroups.get(key) ?? []), itemId]);
  }
  for (const ids of twinGroups.values()) {
    if (ids.length < 2) continue;
    [...ids]
      .sort(
        (a, b) => addedAt(a).localeCompare(addedAt(b)) || a.localeCompare(b),
      )
      .forEach((id, index) =>
        twinOf.set(id, {
          position: index + 1,
          of: ids.length,
          added: addedAt(id) || null,
        }),
      );
  }

  const levelMatches = (itemId: string): boolean => {
    if (!locationLevelFilter) return true;
    const loc = getStockTakeItem(itemId)?.shelf_location ?? "";
    return loc.split("-")[0] === locationLevelFilter;
  };
  const onShelf = (itemId: string): boolean =>
    !shelfId || getStockTakeItem(itemId)?.location_id === shelfId;
  const visibleIds = orderedIds.filter(
    (itemId) => levelMatches(itemId) && onShelf(itemId),
  );

  if (visibleIds.length === 0) {
    // "Nothing was expected here" is a statement about the shelf, so it is
    // made only when the shelf has no row at all — not when a filter hides them.
    const shelfMessage = allItemIds.some(onShelf)
      ? t("stock_takes:shelf.hidden")
      : t("stock_takes:shelf.empty");
    return (
      <div className="bg-surface-card rounded-xl p-8 text-center border">
        <Package className="mx-auto text-on-muted mb-3" size={48} />
        <p className="text-on-secondary">
          {shelfId ? shelfMessage : t("stock_takes:noItemsCounted")}
        </p>
        {!shelfId && (
          <p className="text-sm text-on-muted mt-1">
            {t("stock_takes:searchToCount")}
          </p>
        )}
      </div>
    );
  }

  return (
    <div className="space-y-2">
      {visibleIds.map((itemId) => {
        const item = getItemById(itemId);
        const stockTakeItem = getStockTakeItem(itemId);
        const counted = countedQuantities[itemId] ?? "";
        const savedCount = toAmount(stockTakeItem?.counted_quantity);
        const discrepancy = getDiscrepancyType(itemId);
        // an uncounted line is not "saved" — only an explicit
        // count equal to the server value disables the save button.
        const isSaved = counted !== "" && !isUnsaved(itemId);

        return (
          <StockTakeItemCard
            key={itemId}
            itemId={itemId}
            item={item}
            stockTakeItem={stockTakeItem}
            counted={counted}
            savedCount={savedCount}
            discrepancy={discrepancy}
            twin={twinOf.get(itemId) ?? null}
            isSaved={isSaved}
            isUnsaved={isUnsaved(itemId)}
            awaitingRecount={Boolean(stockTakeItem?.recount_requested)}
            counts={stockTakeItem?.counts ?? []}
            onRequestRecount={onRequestRecount}
            isUpdatePending={isUpdatePending}
            isInProgress={stockTakeStatus === "in_progress"}
            blindMode={blindMode}
            note={notes[itemId] || ""}
            reasonCode={reasons[itemId]?.code ?? ""}
            reasonNote={reasons[itemId]?.note ?? ""}
            showReasonErrors={Boolean(triedToSave[itemId])}
            reasonRequired={reasonRequired}
            onReasonChange={onReasonChange}
            onNoteChange={onNoteChange}
            onQuantityChange={onQuantityChange}
            onQuantityStep={onQuantityStep}
            onSave={onSave}
          />
        );
      })}
    </div>
  );
}
