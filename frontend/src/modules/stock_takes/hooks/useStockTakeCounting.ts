import { useState, useCallback, useRef } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import { toAmount } from "@/utils/formatters";
import { unitLabel } from "@/lib/i18nHelpers";
import {
  useStockTake,
  useAddStockTakeItem,
  useCountStockTakeItem,
  useCancelStockTake,
  useRequestRecount,
} from "@/modules/stock_takes/hooks/useStockTakes";
import { useCompleteStockTakeFlow } from "@/modules/stock_takes/hooks/useCompleteStockTakeFlow";
import { useStorageItems } from "@/modules/shared/hooks/useStorages";
import { useCreateItem, useItemSearch } from "@/modules/inventory/moduleApi";
import type { Item } from "@/types";
import type { StockTakeItem } from "@/modules/stock_takes/types/stock-takes";
import { toast } from "sonner";
import { useConfirm } from "@/hooks/useConfirm";
import { reasonIsComplete } from "@/modules/shared/components/ReasonCodeField";
import { useCountingDrafts } from "@/modules/stock_takes/hooks/useCountingDrafts";
import { useShelfCounting } from "@/modules/stock_takes/hooks/useShelfCounting";
import {
  countedAmount,
  countedText,
  decimalsAllowedBy,
  fitsUnitStep,
} from "@/modules/stock_takes/countingQuantity";
import { useFormGuard } from "@/hooks/useFormGuard";
import { extractApiError, isNotFoundError } from "@/lib/errors";

/**
 * The search asks the whole organization, but a counter at a shelf means
 * what is on it: the hits of this count — on its list or in its place —
 * come first, the rest of the organization after them.
 *
 * The place's own matches arrive from a search scoped to it, because the
 * organization's page is cut before this function sees it: a shelf holding
 * one matching record can fall behind a hundred matches elsewhere and never
 * reach the "here" group at all.
 */
function splitByPlace(
  hereHits: Item[],
  orgHits: Item[],
  hereItemIds: Set<string>,
): [Item[], Item[]] {
  const here = [...hereHits];
  const seen = new Set(here.map((item) => item.id));
  const elsewhere: Item[] = [];
  for (const item of orgHits) {
    if (seen.has(item.id)) continue;
    if (hereItemIds.has(item.id)) {
      here.push(item);
    } else {
      elsewhere.push(item);
    }
    seen.add(item.id);
  }
  return [here, elsewhere];
}

/**
 * The count's search: what stands in the counted place first, the rest of the
 * organization after it.
 *
 * The place is asked on its own because the organization's page is cut by
 * creation date — a record standing here can sit behind a hundred matches
 * elsewhere and never reach the first group. A failed half is said as a
 * failed search: silence about the place would read as "nothing is here",
 * the one answer this grouping exists to avoid.
 */
function useCountSearch(
  query: string,
  locationId: string | undefined,
  listedItemIds: Set<string>,
  locationItems: Item[],
): [Item[], Item[], boolean] {
  // "Here" is the count's own list plus everything standing in the counted
  // place and below it — the count claims the location and its descendants.
  const hereItemIds = new Set(listedItemIds);
  for (const item of locationItems) hereItemIds.add(item.id);
  const { data: hereResults, isError: hereFailed } = useItemSearch(
    query,
    locationId,
  );
  const { data: orgResults, isError: orgFailed } = useItemSearch(query);
  const [here, elsewhere] = splitByPlace(
    hereResults?.items ?? [],
    orgResults?.items ?? [],
    hereItemIds,
  );
  return [here, elsewhere, hereFailed || orgFailed];
}

/** The live list of a place, whether the API answers an array or a page. */
function itemList(raw: Item[] | { items?: Item[] } | undefined): Item[] {
  return Array.isArray(raw) ? raw : (raw?.items ?? []);
}

/** The boxes of the "new product" form: what a counter types for goods the
 *  organization has no record of yet. */
function useNewItemDraft() {
  const [newItemName, setNewItemName] = useState("");
  const [newItemBarcode, setNewItemBarcode] = useState("");
  const [newItemQuantity, setNewItemQuantity] = useState(1);
  const [newItemCategoryId, setNewItemCategoryId] = useState("");
  const [newItemUomId, setNewItemUomId] = useState("");
  return {
    newItemName,
    setNewItemName,
    newItemBarcode,
    setNewItemBarcode,
    newItemQuantity,
    setNewItemQuantity,
    newItemCategoryId,
    setNewItemCategoryId,
    newItemUomId,
    setNewItemUomId,
    /** Empty again once the product is created — category and unit stay. */
    reset: () => {
      setNewItemName("");
      setNewItemBarcode("");
      setNewItemQuantity(1);
    },
  };
}

/**
 * Whether a saved count is still on its way back to the screen.
 *
 * Finishing is judged on the rows on screen, which still say "not counted"
 * until the read after the save is here, so it waits for that read: pressed
 * right after Save, it refused with "one product is still uncounted". The read
 * stays outside the chain of saves, so a scan's next save need not wait for it.
 */
function useSavesInFlight(
  refetch: (options: { cancelRefetch: boolean }) => Promise<unknown>,
) {
  const [inFlight, setInFlight] = useState(0);
  const trackSave = (saved: Promise<void>) => {
    setInFlight((count) => count + 1);
    void saved
      .then(() => refetch({ cancelRefetch: false }))
      .finally(() => setInFlight((count) => count - 1));
    return saved;
  };
  return { isSavingCounts: inFlight > 0, trackSave };
}

export function useStockTakeCounting(id: string | undefined) {
  const { t } = useTranslation(["stock_takes"]);
  const navigate = useNavigate();
  const [searchQuery, setSearchQuery] = useState("");
  const [showDiscrepancies, setShowDiscrepancies] = useState(false);
  const [isAddingNewItem, setIsAddingNewItem] = useState(false);
  const newItemDraft = useNewItemDraft();
  const [locationLevelFilter, setLocationLevelFilter] = useState("");
  const { confirm, confirmDialogProps } = useConfirm();

  const {
    data: stockTake,
    isLoading,
    isError,
    error,
    refetch,
  } = useStockTake(id);
  const { data: storageItems } = useStorageItems(stockTake?.location_id || "");

  // What the reader has typed but not yet saved lives here; everything that
  // counts or summarises reads the stock take's own rows instead.
  const {
    countedQuantities,
    setCountedQuantities,
    notes,
    setNotes,
    reasons,
    setReasons,
    triedToSave,
    setTriedToSave,
    handleQuantityChange,
    handleQuantityStep,
    oneMoreThan,
  } = useCountingDrafts(stockTake);

  const { isSavingCounts, trackSave } = useSavesInFlight(refetch);
  const countMutation = useCountStockTakeItem(id);
  const recountMutation = useRequestRecount(id);
  const recountMutate = recountMutation.mutate;
  const surplusMutation = useAddStockTakeItem(id);
  const cancelMutation = useCancelStockTake();
  const createItemMutation = useCreateItem();
  // Stable refs for useCallback deps — the mutation result objects are
  // recreated every render.
  const cancelMutate = cancelMutation.mutate;
  // Saves leave one after another. A count is an absolute number and the
  // server keeps whichever arrives last, so two scans of one shelf sent side
  // by side stored 3 after 4 whenever the first request was the slow one —
  // the screen said 4, the stock take said 3, and nothing said a scan was lost.
  const savesRef = useRef<Promise<void>>(Promise.resolve());
  // Rows the surplus endpoint created that the stock take on screen may not
  // carry yet: the next scan of the same record counts onto that row rather
  // than asking to create it a second time.
  const createdLinesRef = useRef<Record<string, string>>({});

  const handleAddItem = (item: Item) => {
    if (!item.id) return;
    const existingItem = stockTake?.items?.find((i) => i.item_id === item.id);
    if (existingItem) {
      handleQuantityStep(item.id, 1);
    } else {
      setCountedQuantities((prev) => ({ ...prev, [item.id]: "1" }));
    }
    setSearchQuery("");
    setIsAddingNewItem(false);
  };

  const handleAddNewItem = (payload: {
    name: string;
    barcode: string;
    quantity: number;
    categoryId?: string;
    uomId?: string;
  }) => {
    // Create the product in the counted location, then
    // register it as a surplus on the stock take. Replaces the old
    // in-memory temp id that no endpoint could ever save.
    if (!payload.name.trim() || !stockTake?.location_id) return;
    createItemMutation.mutate(
      {
        name: payload.name.trim(),
        barcode: payload.barcode.trim() || undefined,
        // Opened holding nothing: the counted quantity is the surplus row's,
        // and the count posts it when it closes. Created with it, the goods
        // were on the shelf before the count was closed — a cancelled count
        // left them there — and the row's baseline read the same number as
        // its count, so the correction document had no line for them.
        quantity: 0,
        category_id: payload.categoryId || undefined,
        uom_id: payload.uomId || undefined,
        // Created beside the counted stock; no template match to contradict —
        // the flag's "no", which the server used to default to.
        unit_confirmed_over_template: false,
        location_id: stockTake.location_id,
      },
      {
        onSuccess: (created) => {
          surplusMutation.mutate({
            itemId: created.id,
            quantity: payload.quantity,
          });
          setSearchQuery("");
          setIsAddingNewItem(false);
          newItemDraft.reset();
        },
      },
    );
  };

  /** Save one row — what its box holds, or the `text` a scan just put there. */
  const handleSaveItem = (
    itemId: string,
    text: string | undefined = countedQuantities[itemId],
  ) => {
    // items already on the stock take list are saved through
    // PATCH …/items/{StockTakeItem.id}/count; only items found outside
    // the list go through the surplus endpoint (POST …/items).
    const line = getStockTakeItem(itemId);
    const quantity = countedAmount(text) ?? 0;
    const itemNotes = notes[itemId] || "";
    const reason = reasons[itemId] ?? { code: "" as const, note: "" };

    // The unit says how finely its quantity may be stated, and the server
    // checks it on the way in. Asked here first, the answer arrives while the
    // person is still standing at the shelf and the number is still on the
    // card — a refusal after the save takes the count off the card with it.
    if (!fitsUnitStep(quantity, line?.uom_rounding)) {
      // The refusal names the unit; the name is the reader's word for it, not
      // the record's symbol ("pcs" inside an English sentence is readable,
      // "pcs" inside a Polish one is not).
      const unit = unitLabel(t, line?.uom_symbol);
      const places = decimalsAllowedBy(line?.uom_rounding);
      toast.error(
        places === 0
          ? t("stock_takes:errors.unitIsWhole", { unit })
          : t("stock_takes:errors.unitDecimals", { unit, count: places }),
      );
      return;
    }

    // "Other" carries nothing on its own, so there the note is the reason.
    // Refused here rather than by the server, because a rejected save takes
    // the count back off the card and the reader loses the number too.
    if (reason.code !== "" && !reasonIsComplete(reason.code, reason.note)) {
      setTriedToSave((prev) => ({ ...prev, [itemId]: true }));
      toast.error(t("stock_takes:errors.reasonIncomplete"));
      return;
    }
    const reasonFields = {
      discrepancy_reason_code: reason.code || null,
      discrepancy_reason: reason.note.trim() || null,
    };

    // The card and the progress counter are drawn from this local state, so a
    // save the server refused left "Counted: 4" and "1 / 5" on a shelf nobody
    // counted — and the reader moved on to the next bay. Putting the previous
    // value back is what keeps the count honest; the message has to be raised
    // here too, because handling the error at the call site is what tells
    // `useAppMutation` to stay quiet.
    const rollback = (error: Error) => {
      setCountedQuantities((prev) => ({
        ...prev,
        // Back the way the box writes it, not the way the column stores it:
        // the wire says "2.150" and every other route into this field says
        // "2.15".
        [itemId]: countedText(line?.counted_quantity),
      }));
      setNotes((prev) => ({ ...prev, [itemId]: line?.notes ?? "" }));
      toast.error(extractApiError(error, t("stock_takes:errors.saveFailed")));
    };

    const write = async () => {
      const lineId = line?.id ?? createdLinesRef.current[itemId];
      if (lineId) {
        await countMutation.mutateAsync({
          stockTakeItemId: lineId,
          quantity,
          notes: itemNotes,
          ...reasonFields,
        });
      } else {
        const created = await surplusMutation.mutateAsync({
          itemId,
          quantity,
          notes: itemNotes,
        });
        createdLinesRef.current[itemId] = created.id;
      }
    };
    savesRef.current = trackSave(savesRef.current.then(write).catch(rollback));
  };

  const shelfCounting = useShelfCounting({
    stockTake,
    confirm,
    isUnsaved: (itemId) => isUnsaved(itemId), // declared below, read on close
    surplusMutation,
    countMutation,
    savesRef,
    createdLinesRef,
    handleQuantityChange,
    oneMoreThan,
    onDone: () => setSearchQuery(""),
  });

  /** A scan: one more on the row, saved without a press of its Save. */
  const countOneMore = (itemId: string) => {
    const next = oneMoreThan(itemId);
    handleQuantityChange(itemId, next);
    handleSaveItem(itemId, next);
  };

  /** Send one row back to be counted again — the row keeps its number. */
  const handleRequestRecount = (itemId: string) => {
    const line = getStockTakeItem(itemId);
    if (!line) return;
    recountMutate({ stockTakeItemId: line.id });
  };

  const handleCancel = useCallback(async () => {
    if (
      await confirm({
        title: t("confirm.cancel.title"),
        message: t("confirm.cancel.message"),
        variant: "danger",
        confirmLabel: t("confirm.cancel.confirmLabel"),
      })
    ) {
      cancelMutate(id!, {
        onSuccess: () => navigate("/inventory/stock-takes"),
      });
    }
  }, [confirm, cancelMutate, navigate, id, t]);

  const getItemById = (itemId: string): Item | undefined =>
    itemList(storageItems).find((item) => item.id === itemId);

  const getStockTakeItem = (itemId: string): StockTakeItem | undefined =>
    stockTake?.items?.find((item) => item.item_id === itemId);

  /** What the stock take holds for a product, as opposed to what the input
   * box currently shows. Every summary on this screen reads this one. */
  const savedQuantityOf = (itemId: string): number | null =>
    toAmount(getStockTakeItem(itemId)?.counted_quantity);

  /** Whether the row says something the stock take does not know yet.
   *
   * The reason counts as much as the number does. Left out, picking "Damaged"
   * on a row whose count was already saved changed nothing: the save button
   * stays disabled on a row that agrees with the record, so the reason had no
   * way to reach the server and no mark to say it had not. */
  const isUnsaved = (itemId: string): boolean => {
    const line = getStockTakeItem(itemId);
    const reason = reasons[itemId] ?? { code: "", note: "" };
    return (
      countedAmount(countedQuantities[itemId]) !== savedQuantityOf(itemId) ||
      reason.code !== (line?.discrepancy_reason_code ?? "") ||
      reason.note.trim() !== (line?.discrepancy_reason ?? "")
    );
  };

  // Whether a row is a discrepancy is the server's answer, not this screen's
  // arithmetic. A stock take may carry a tolerance — a difference small
  // enough that nobody is expected to explain it — and the rule lives in one
  // place, next to the write. Recomputed here as "counted != system", the
  // screen flagged rows the report did not, so the same count read two ways
  // gave two numbers and the wrong one was the one under the counter's nose.
  const hasDiscrepancy = (itemId: string): boolean =>
    getStockTakeItem(itemId)?.is_discrepancy === 1;

  // Which way it went is arithmetic, and stays here: the flag says whether
  // the difference counts, the numbers say which direction it goes.
  const getDiscrepancyType = (itemId: string): "missing" | "surplus" | null => {
    const stockTakeItem = getStockTakeItem(itemId);
    if (!hasDiscrepancy(itemId)) return null;
    if (!stockTakeItem || stockTakeItem.system_quantity === null) return null;
    const counted = savedQuantityOf(itemId);
    if (counted == null) return null;
    // A unit found away from the location it is recorded on keeps its one
    // row, moved to where it was found, and is flagged even when the number
    // agrees. On this location nothing of it was expected — the report says
    // the same — and read from the numbers alone it was no difference at
    // all, which hid the reason a tolerance then refused to close without.
    if (stockTakeItem.expected_location_id) return "surplus";
    const system = Number(stockTakeItem.system_quantity);
    if (counted < system) return "missing";
    if (counted > system) return "surplus";
    return null;
  };

  const allItemIds = Object.keys(countedQuantities);
  // progress is driven only by items that belong to the stock
  // take; products found outside the list (surpluses) get their own
  // counter and must not inflate "3 / 3 counted" or "1 / 0 items".
  const listedItemIds = new Set(
    (stockTake?.items ?? [])
      .map((item) => item.item_id)
      .filter((itemId): itemId is string => Boolean(itemId)),
  );
  // products present in the location but not in the stock take
  // snapshot — the snapshot is silently silent about them otherwise.
  const locationItems = itemList(storageItems);
  const outsideItems = locationItems.filter(
    (item) => !listedItemIds.has(item.id),
  );
  const surplusItemIds = allItemIds.filter((id) => !listedItemIds.has(id));
  const [searchHere, searchElsewhere, searchFailed] = useCountSearch(
    searchQuery,
    stockTake?.location_id,
    listedItemIds,
    locationItems,
  );
  // Progress counts rows the stock take holds, not rows somebody typed into.
  // A number in the box is one button press away from being a count and is
  // gone the moment the screen is left; counted here, the bar read "2 / 6"
  // over a stock take the server knew as "1 / 6" and said so for the whole
  // hour of counting. This is the same number the server publishes as
  // `counted_items_count`, derived from the rows so that the bar and the
  // cards can never disagree.
  const countedCount = (stockTake?.items ?? []).filter(
    (item) => item.counted_quantity != null,
  ).length;
  // Surpluses stay a count of what is on screen: a saved one joins the stock
  // take's own rows and is counted above, so a saved-only reading would
  // always be zero.
  const surplusCount = surplusItemIds.filter(
    (itemId) => countedAmount(countedQuantities[itemId]) !== null,
  ).length;
  const locationLevels = [
    ...new Set(
      (stockTake?.items ?? [])
        .map((item) => item.shelf_location?.split("-")[0])
        .filter((level): level is string => Boolean(level)),
    ),
  ].sort();
  const totalCount = stockTake?.items_count || 0;
  const progress = totalCount > 0 ? (countedCount / totalCount) * 100 : 0;
  // The same number the server publishes as `discrepancies_count`.
  const discrepanciesCount =
    stockTake?.items?.filter((item) => item.is_discrepancy === 1).length || 0;
  const unsavedCount = allItemIds.filter(isUnsaved).length;

  // The shared gate the module tabs, the mobile bar and the header's back
  // arrow all route through. Counting is a form like any other here: what is
  // in the boxes is unsaved work, and walking off the screen threw it away
  // without a word — an hour of shelf counting for one tap on the wrong tab.
  useFormGuard(unsavedCount > 0, t("stock_takes:form.guardName"));

  // Declared here rather than beside the other mutations because the
  // confirmation has to name the rows still sitting in their boxes.
  const { handleComplete, completeMutation } = useCompleteStockTakeFlow(
    id,
    stockTake?.items,
    confirm,
    unsavedCount,
    stockTake?.require_full_count ?? false,
  );

  return {
    stockTake,
    isLoading,
    // A count that "does not exist" reads to the person walking the shelf as
    // work lost. Only a 404 says that; a 500 says the question went unanswered.
    isNotFound: isNotFoundError(error),
    isError,
    refetch,
    searchQuery,
    setSearchQuery,
    showDiscrepancies,
    setShowDiscrepancies,
    isAddingNewItem,
    setIsAddingNewItem,
    ...newItemDraft,
    createItemMutation,
    locationLevelFilter,
    setLocationLevelFilter,
    locationLevels,
    countedQuantities,
    notes,
    setNotes,
    reasons,
    setReasons,
    triedToSave,
    countMutation,
    completeMutation,
    isSavingCounts,
    handleQuantityChange,
    handleQuantityStep,
    handleAddItem,
    handleAddNewItem,
    handleSaveItem,
    countOneMore,
    shelfCounting,
    handleRequestRecount,
    handleComplete,
    handleCancel,
    getItemById,
    getStockTakeItem,
    hasDiscrepancy,
    getDiscrepancyType,
    isUnsaved,
    allItemIds,
    outsideItems,
    countedCount,
    surplusCount,
    totalCount,
    progress,
    discrepanciesCount,
    unsavedCount,
    confirmDialogProps,
    searchHere,
    searchElsewhere,
    searchFailed,
  };
}
