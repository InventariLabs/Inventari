import { useCallback, useEffect, useRef } from "react";
import { useTranslation } from "react-i18next";
import { useParams } from "react-router-dom";
import { CheckCircle, EyeOff, XCircle } from "lucide-react";
import type { Item } from "@/types";
import LoadingSpinner from "@/components/LoadingSpinner";
import { RecordNotFound } from "@/components/ui/RecordNotFound";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { Button } from "@/components/ui/Button";
import { QueryError } from "@/components/ui/QueryResult";
import { useModulePageHeader } from "@/hooks/useModulePageHeader";
import { useStockTakeCounting } from "../hooks/useStockTakeCounting";
import { useScanCounting } from "../hooks/useScanCounting";
import StockTakeScanChooser from "../components/StockTakeScanChooser";
import StockTakeProgress from "../components/StockTakeProgress";
import StockTakeSearchSection from "../components/StockTakeSearchSection";
import StockTakeOutsideItemsBar from "../components/StockTakeOutsideItemsBar";
import StockTakeFilters from "../components/StockTakeFilters";
import StockTakeItemsList from "../components/StockTakeItemsList";
import StockTakeShelfBar from "../components/StockTakeShelfBar";
import { useCanWrite } from "@/hooks/useCanWrite";
import { ReadOnlyNotice } from "@/components/ui/ReadOnlyNotice";

export default function StockTakeCountingPage() {
  const { t } = useTranslation(["stock_takes", "common"]);
  const { id } = useParams<{ id: string }>();
  const { setHeader } = useModulePageHeader();
  const canWrite = useCanWrite("stock_takes");
  const {
    stockTake,
    isLoading,
    isNotFound,
    isError,
    refetch,
    searchQuery,
    setSearchQuery,
    showDiscrepancies,
    setShowDiscrepancies,
    isAddingNewItem,
    setIsAddingNewItem,
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
  } = useStockTakeCounting(id);

  // choosing a fuzzy search hit must not silently add +1 to the
  // wrong product — it scrolls to the card and highlights it; only an
  // exact barcode match adds the quantity immediately.
  // The scroll-and-highlight timers are owned by this page: both ids live in
  // a ref and unmount takes them back — "touches only DOM" is not a safety
  // reason, because after a test-environment teardown `document` disappears
  // exactly like `window`.
  const scrollTimersRef = useRef<number[]>([]);

  useEffect(() => {
    return () => {
      for (const id of scrollTimersRef.current) clearTimeout(id);
      scrollTimersRef.current = [];
    };
  }, []);

  const scrollToItemCard = useCallback((itemId: string) => {
    for (const id of scrollTimersRef.current) clearTimeout(id);
    scrollTimersRef.current = [];
    const scrollTimer = window.setTimeout(() => {
      const card = document.querySelector(
        `[data-item-id="${CSS.escape(itemId)}"]`,
      );
      if (!card) return;
      card.scrollIntoView({ behavior: "smooth", block: "center" });
      card.classList.add("stock-take-card-highlight");
      const highlightTimer = window.setTimeout(
        () => card.classList.remove("stock-take-card-highlight"),
        1500,
      );
      scrollTimersRef.current.push(highlightTimer);
    }, 100);
    scrollTimersRef.current.push(scrollTimer);
  }, []);

  const handleSearchSelect = useCallback(
    (item: Item) => {
      const isListed = Boolean(
        stockTake?.items?.some((line) => line.item_id === item.id),
      );
      const exactBarcode =
        Boolean(item.barcode) && item.barcode!.trim() === searchQuery.trim();
      // A product not on the stock take list has no card to scroll
      // to — the search result is the only path to register an existing
      // product as a surplus, so add it. Listed items only scroll and
      // highlight; only an exact barcode match adjusts the quantity.
      if (!isListed || exactBarcode) {
        handleAddItem(item);
      } else {
        setSearchQuery("");
      }
      scrollToItemCard(item.id);
    },
    [searchQuery, stockTake, handleAddItem, setSearchQuery, scrollToItemCard],
  );

  // A scan is a count: the row it names gets one more and is saved, and the
  // card is brought into view so the reader sees the number move.
  const scanCounting = useScanCounting({
    lines: stockTake?.items ?? [],
    outsideItemIds: outsideItems.map((item) => item.id),
    onCount: (itemId) => {
      countOneMore(itemId);
      setSearchQuery("");
      scrollToItemCard(itemId);
    },
    onMiss: setSearchQuery,
    countedLocations: stockTake?.counted_locations ?? [],
    shelf: shelfCounting.shelf,
    onShelf: shelfCounting.setShelf,
    onShelfOutside: shelfCounting.refuseShelfOutside,
    onFoundOnShelf: shelfCounting.countFoundOnShelf,
  });

  useEffect(() => {
    if (!stockTake) {
      setHeader({});
      return;
    }

    const actions: React.ReactNode[] = [];
    if (stockTake.status === "in_progress") {
      actions.push(
        <Button
          size="content"
          key="cancel"
          type="button"
          variant="outline"
          data-testid="stock-take-cancel-btn"
          onClick={handleCancel}
          className="px-4 py-2 border border-red-300 text-red-600 dark:text-red-400 dark:border-red-500/40 rounded-lg hover:bg-red-50 dark:hover:bg-red-500/10"
        >
          <XCircle size={18} />
          {t("stock_takes:actions.cancel")}
        </Button>,
        <Button
          size="content"
          key="complete"
          type="button"
          variant="primary"
          data-testid="stock-take-complete-btn"
          onClick={handleComplete}
          disabled={completeMutation.isPending}
          className="px-4 py-2"
        >
          <CheckCircle size={18} />
          {completeMutation.isPending
            ? t("stock_takes:actions.completing")
            : t("stock_takes:actions.complete")}
        </Button>,
      );
    }

    setHeader({
      title: stockTake.name,
      subtitle: stockTake.location_name ?? undefined,
      backTo: "/inventory/stock-takes",
      actions: actions.length > 0 ? <>{actions}</> : undefined,
    });
  }, [
    stockTake,
    setHeader,
    handleCancel,
    handleComplete,
    completeMutation.isPending,
    t,
  ]);

  if (isLoading) return <LoadingSpinner />;

  // A failed request is not a deleted stock take: telling someone halfway
  // through counting a bay that their count does not exist reads as work lost.
  if (isError && !isNotFound) return <QueryError onRetry={refetch} />;

  if (!stockTake) {
    return (
      <RecordNotFound
        title={t("stock_takes:notFound")}
        backTo="/inventory/stock-takes"
        backLabel={t("common:actions.back")}
      />
    );
  }

  // Counting is writing. The list this page is opened from asks first, so an
  // account without the right never sees the way in — but the address is one
  // anybody can type, and the whole counting screen used to open on it.
  if (!canWrite) {
    return (
      <div className="space-y-4">
        <ReadOnlyNotice module="stock_takes" />
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {stockTake.blind_mode && (
        // blind mode silently removed the expected quantities —
        // make the mode visible so the counter understands why.
        <div className="flex items-center gap-2 text-sm text-amber-700 dark:text-amber-400 bg-amber-50 dark:bg-amber-500/10 border border-amber-200 dark:border-amber-500/20 rounded-lg px-3 py-2">
          <EyeOff size={16} className="shrink-0" />
          {t("stock_takes:blindModeActive")}
        </div>
      )}

      <StockTakeProgress
        countedCount={countedCount}
        totalCount={totalCount}
        progress={progress}
        discrepanciesCount={discrepanciesCount}
        unsavedCount={unsavedCount}
      />

      {stockTake.status === "in_progress" && (
        <StockTakeShelfBar
          counting={shelfCounting}
          closedLocations={stockTake.closed_locations}
        />
      )}

      <StockTakeSearchSection
        status={stockTake.status}
        searchQuery={searchQuery}
        onSearchChange={setSearchQuery}
        searchHere={searchHere}
        searchElsewhere={searchElsewhere}
        searchFailed={searchFailed}
        onSubmitCode={(code) => void scanCounting.countByCode(code)}
        isAddingNewItem={isAddingNewItem}
        onToggleAddNewItem={() => setIsAddingNewItem(!isAddingNewItem)}
        newItemName={newItemName}
        onNewItemNameChange={setNewItemName}
        newItemBarcode={newItemBarcode}
        onNewItemBarcodeChange={setNewItemBarcode}
        newItemQuantity={newItemQuantity}
        onNewItemQuantityChange={setNewItemQuantity}
        newItemCategoryId={newItemCategoryId}
        onNewItemCategoryIdChange={setNewItemCategoryId}
        newItemUomId={newItemUomId}
        onNewItemUomIdChange={setNewItemUomId}
        createPending={createItemMutation.isPending}
        createError={createItemMutation.error}
        onAddItem={handleSearchSelect}
        onCreateNewItem={() =>
          handleAddNewItem({
            name: newItemName,
            barcode: newItemBarcode,
            quantity: newItemQuantity,
            categoryId: newItemCategoryId || undefined,
            uomId: newItemUomId || undefined,
          })
        }
      />

      {stockTake.status === "in_progress" && (
        <StockTakeOutsideItemsBar items={outsideItems} onAdd={handleAddItem} />
      )}

      <StockTakeFilters
        showDiscrepancies={showDiscrepancies}
        onShowAll={() => setShowDiscrepancies(false)}
        onShowDiscrepancies={() => setShowDiscrepancies(true)}
        totalCount={totalCount}
        discrepanciesCount={discrepanciesCount}
        surplusCount={surplusCount}
        locationLevels={locationLevels}
        locationLevelFilter={locationLevelFilter}
        onLocationLevelFilterChange={setLocationLevelFilter}
      />

      <StockTakeItemsList
        allItemIds={allItemIds}
        showDiscrepancies={showDiscrepancies}
        countedQuantities={countedQuantities}
        notes={notes}
        reasons={reasons}
        triedToSave={triedToSave}
        reasonRequired={stockTake.tolerance_percent != null}
        stockTakeStatus={stockTake.status}
        blindMode={stockTake.blind_mode || false}
        isUpdatePending={countMutation.isPending}
        locationLevelFilter={locationLevelFilter}
        shelfId={shelfCounting.shelf?.id ?? null}
        getItemById={getItemById}
        getStockTakeItem={getStockTakeItem}
        hasDiscrepancy={hasDiscrepancy}
        getDiscrepancyType={getDiscrepancyType}
        isUnsaved={isUnsaved}
        onNoteChange={(itemId, value) =>
          setNotes((prev) => ({ ...prev, [itemId]: value }))
        }
        onReasonChange={(itemId, reason) =>
          setReasons((prev) => ({ ...prev, [itemId]: reason }))
        }
        onQuantityChange={handleQuantityChange}
        onQuantityStep={handleQuantityStep}
        onSave={handleSaveItem}
        onRequestRecount={handleRequestRecount}
      />

      <StockTakeScanChooser
        rows={scanCounting.choices}
        getItemById={getItemById}
        onChoose={scanCounting.choose}
        onClose={scanCounting.dismissChoices}
      />

      <ConfirmDialog {...confirmDialogProps} />
    </div>
  );
}
