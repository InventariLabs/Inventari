import { useState, useEffect, useCallback, useRef } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { StorageRequired } from "@/modules/shared/components/StorageRequired";
import { labelsApi } from "@/lib/api/labels";
import { useLocationOffer } from "@/module-sdk";
import type { LabelScanView } from "@/types";
import type { ItemFormData } from "@/modules/inventory/hooks/useItemForm";
import {
  useScanConsume,
  useScanUsePartially,
  useScanUpdateQuantity,
  useScanAddToShoppingList,
} from "@/modules/inventory/hooks/useScanActions";
import QuickAddModal from "@/modules/inventory/components/QuickAddModal";
import QuickActionSheet from "@/modules/inventory/components/QuickActionSheet";
import ArchivedItemSheet from "../components/ArchivedItemSheet";
import StockActionSheet from "../components/StockActionSheet";
import ItemEditModal from "../components/ItemEditModal";
import ScanCameraView, {
  type LookupFailure,
} from "../components/ScanCameraView";
import { LocationContentsSheet } from "@/modules/shared/components/LocationContentsSheet";
import { toast } from "sonner";
import { extractApiError } from "@/lib/errors";
import { useScanStore } from "@/store/scanStore";
import { useScanCamera } from "@/hooks/useScanCamera";
import { useCanWrite } from "@/hooks/useCanWrite";
import { ReadOnlyNotice } from "@/components/ui/ReadOnlyNotice";
import { documentScanTarget } from "@/lib/scan/scanSubject";
import { scanFailure } from "@/lib/scan/toastScanError";

/**
 * What a scanned location label opens. It answers "what is on this shelf"
 * first; making the place the scan context is one of the sheet's actions.
 */
function ScannedLocationSheet({
  data,
  onClose,
}: {
  data: LabelScanView | null;
  onClose: () => void;
}) {
  const { t } = useTranslation("scan");
  const { setStorageContext } = useScanStore();
  const location = data?.location;
  if (data?.action !== "set_storage_context" || !location) return null;
  return (
    <LocationContentsSheet
      location={location}
      onClose={onClose}
      onUseAsContext={() => {
        setStorageContext({
          id: location.id,
          name: location.name,
          icon: location.icon || "📦",
          type_code: location.type_code,
        });
        toast.success(t("storageContextSet", { name: location.name }));
      }}
    />
  );
}

export default function ScanPage() {
  const { t: tScan } = useTranslation("scan");
  const { t: tCommon } = useTranslation("common");
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const { storageContext, setStorageContext } = useScanStore();

  const [scannedLabelData, setScannedLabelData] =
    useState<LabelScanView | null>(null);
  const partly = useScanUsePartially(scannedLabelData, setScannedLabelData);
  const [lookupFailure, setLookupFailure] = useState<LookupFailure | null>(
    null,
  );
  const [showQuickAdd, setShowQuickAdd] = useState(false);
  const [showQuickActions, setShowQuickActions] = useState(false);
  const [showArchivedInfo, setShowArchivedInfo] = useState(false);
  const [showStockActions, setShowStockActions] = useState(false);
  const [showEditModal, setShowEditModal] = useState(false);
  const [editingItemId, setEditingItemId] = useState<string | null>(null);
  const [selectedStorageId, setSelectedStorageId] = useState<string>("");

  // The scanner offers nothing itself, but it has to know whether this screen
  // has anywhere to record into — the same offer its pickers make (the
  // quick-add form it opens is a stock flow), and the same one
  // `StorageRequired` below reads, so the banner and the warning can never
  // disagree about whether an organization has a location.
  const { total: offeredStorages } = useLocationOffer({ purpose: "stock" });
  const hasNoStorages = offeredStorages === 0;

  // Reading a label is a GET that asks for nothing beyond membership, so the
  // scanner itself stays: "what is this thing" is a fair question for an
  // account that may not change anything. What goes is everything the sheets
  // offer afterwards. The shopping list is a second module with a second key,
  // so it is asked separately rather than folded into the first answer.
  const canWrite = useCanWrite("items");
  const canAddToShoppingList = useCanWrite("shopping_lists");

  const consumeMutation = useScanConsume();
  const updateQuantityMutation = useScanUpdateQuantity();
  const addToShoppingListMutation = useScanAddToShoppingList();
  // Stable ref for useCallback deps — the mutation result object is
  // recreated every render.
  const addToShoppingListMutateAsync = addToShoppingListMutation.mutateAsync;

  const handleLabelScanRef = useRef<(code: string) => Promise<void>>();

  const triggerSuccessFeedback = () => navigator.vibrate?.(100);

  const {
    scannerError,
    isCameraActive,
    setIsCameraActive,
    isTorchOn,
    restartCamera,
    resumeCamera,
    pauseCamera,
    toggleTorch,
  } = useScanCamera({
    onCodeScanned: (code: string) => handleLabelScanRef.current?.(code),
  });

  useEffect(() => {
    if (storageContext?.id) {
      setSelectedStorageId(storageContext.id);
    }
  }, [storageContext]);

  useEffect(() => {
    const code = searchParams.get("code");
    if (code) {
      const timer = setTimeout(() => handleLabelScanRef.current?.(code), 100);
      return () => clearTimeout(timer);
    }
  }, [searchParams]);

  const handleLabelScan = async (code: string) => {
    if (!code) return;
    setLookupFailure(null);

    // Batch mode: QuickAddModal already open — just update the label code
    if (showQuickAdd && scannedLabelData) {
      triggerSuccessFeedback();
      setScannedLabelData((prev) =>
        prev ? { ...prev, label_code: code } : null,
      );
      return;
    }

    await pauseCamera();
    triggerSuccessFeedback();

    try {
      const data = await labelsApi.scan(code);
      setScannedLabelData(data);

      if (data.action === "set_storage_context" && data.location) {
        // The location sheet renders from `scannedLabelData`.
      } else if (data.action === "show_quick_add") {
        // A blank label has one use: creating the record it will name. There
        // is nothing to show a reader who may not create one, so the refusal
        // arrives here rather than after the form has been filled in.
        if (!canWrite) {
          toast.error(tCommon("access.readOnly"));
          resumeCamera();
          return;
        }
        // The label itself says what it is for. A blank label carries the
        // context_tag it was generated with (see LabelGenerateModal), so a
        // sheet printed as asset labels lands in the equipment form and a
        // sheet printed as product labels does not — no mode to set first.
        if (data.context_tag === "equipment") {
          navigate("/equipment/add", {
            state: {
              labelCode: data.label_code,
              template: data.stock_summary?.template,
            },
          });
        } else {
          setShowQuickAdd(true);
        }
      } else if (data.action === "show_quick_actions") {
        setShowQuickActions(true);
      } else if (data.action === "show_archived_info") {
        setShowArchivedInfo(true);
      } else if (data.action === "show_stock_actions") {
        setShowStockActions(true);
      } else {
        // A scanned printout opens its document. Where it opens is
        // one decision, shared with every other scanning screen —
        // it used to be spelled out here and nowhere else.
        const documentTarget = documentScanTarget(data);
        if (documentTarget) navigate(documentTarget);
      }
    } catch (error) {
      // the API distinguishes an unrecognized code from a label-format
      // code with no label; surface its message instead of a generic one.
      // It stays on the page: a typed code that nothing matched is an answer
      // to read, not a notification to miss.
      setLookupFailure(scanFailure(error, code, tScan, navigate));
      resumeCamera();
    }
  };

  handleLabelScanRef.current = handleLabelScan;

  /**
   * Read the scanned label again after a quantity changed. The reserved and
   * free figures of a record depend on its siblings in the same hold, so the
   * server redistributes them; patching one number locally would leave the
   * rest of the row stale. A label with nothing left closes the sheet.
   */
  const refreshStockSheet = useCallback(async () => {
    if (!scannedLabelData) return;
    const data = await labelsApi.scan(scannedLabelData.label_code);
    if (
      data.action === "show_stock_actions" &&
      data.stock_summary?.items.length
    ) {
      setScannedLabelData(data);
    } else {
      setShowStockActions(false);
      resumeCamera();
    }
  }, [scannedLabelData, resumeCamera]);

  /**
   * Taking stock off a scanned label: one unit of the record with the nearest
   * expiry.
   *
   * The button under the list says "Remove 1 (first to expire)", and this is the only entry to
   * that rule; it used to take the whole record, so a reader asking for one
   * kilogram lost both. The per-location "−" asks the same question and
   * answers it the same way.
   */
  const handleStockConsume = useCallback(
    async (itemId?: string) => {
      let itemToConsumeId = itemId;
      if (scannedLabelData?.stock_summary?.items?.length) {
        const items = scannedLabelData.stock_summary.items;
        if (!itemToConsumeId) {
          const itemToConsume = [...items].sort((a, b) => {
            if (!a.expiry_date) return 1;
            if (!b.expiry_date) return -1;
            return (
              new Date(a.expiry_date).getTime() -
              new Date(b.expiry_date).getTime()
            );
          })[0];
          itemToConsumeId = itemToConsume.id;
        }
      }

      if (!itemToConsumeId) return;

      try {
        await consumeMutation.mutateAsync({
          itemId: itemToConsumeId,
          quantity: 1,
        });

        await refreshStockSheet();
      } catch (error: unknown) {
        // "Error while removing from stock" reads as a breakage; a refusal reads as one
        // too unless the server's own sentence is allowed through.
        toast.error(extractApiError(error, tScan("errorConsuming")));
      }
    },
    [scannedLabelData, consumeMutation, refreshStockSheet, tScan],
  );

  const handleStockAddOne = useCallback(
    async (itemId: string) => {
      try {
        const currentItem = scannedLabelData?.stock_summary?.items.find(
          (it) => it.id === itemId,
        );
        if (!currentItem) return;
        await updateQuantityMutation.mutateAsync({
          itemId,
          quantity: currentItem.quantity + 1,
        });

        await refreshStockSheet();
      } catch (error) {
        toast.error(extractApiError(error, tScan("errorAdding")));
      }
    },
    [scannedLabelData, updateQuantityMutation, refreshStockSheet, tScan],
  );

  const handleStockAdd = () => {
    setShowStockActions(false);
    setShowQuickAdd(true);
  };

  const handleAddToShoppingList = useCallback(async () => {
    const template = scannedLabelData?.stock_summary?.template;
    if (!template) return;
    try {
      await addToShoppingListMutateAsync({
        templateName: template.name,
      });
      setShowStockActions(false);
      resumeCamera();
    } catch (error) {
      toast.error(extractApiError(error, tScan("errorAddToShoppingList")));
    }
  }, [scannedLabelData, addToShoppingListMutateAsync, resumeCamera, tScan]);

  return (
    <div className="fixed inset-x-0 top-14 bottom-[calc(var(--mobile-nav-height)+env(safe-area-inset-bottom,0px))] md:bottom-0 z-[var(--z-app-bar)] lg:relative lg:inset-auto lg:z-auto flex flex-col lg:h-[calc(100dvh-2rem)] bg-black overflow-hidden lg:rounded-2xl lg:m-4 lg:shadow-lg">
      {/* No storages warning banner */}
      {hasNoStorages && (
        <div className="absolute top-0 left-0 right-0 z-50 p-3">
          <StorageRequired variant="banner" purpose="stock" />
        </div>
      )}

      {/* Same slot, same reason: the reader has to learn before scanning that
          this screen will not let them record anything. */}
      {!canWrite && !hasNoStorages && (
        <div className="absolute top-0 left-0 right-0 z-50 p-3">
          <ReadOnlyNotice module="items" />
        </div>
      )}

      <ScanCameraView
        isCameraActive={isCameraActive}
        scannerError={scannerError}
        isTorchOn={isTorchOn}
        storageContext={storageContext}
        onBack={() => navigate(-1)}
        onStartCamera={() => setIsCameraActive(true)}
        onRestartCamera={restartCamera}
        onToggleTorch={toggleTorch}
        onClearStorageContext={() => setStorageContext(null)}
        onManualCode={handleLabelScan}
        lookupFailure={lookupFailure}
        onDismissLookupFailure={() => setLookupFailure(null)}
      />

      {/* Modals & Sheets */}
      {showQuickAdd && scannedLabelData && (
        <QuickAddModal
          labelCode={scannedLabelData.label_code}
          initialStorageId={selectedStorageId}
          initialData={
            scannedLabelData.stock_summary?.template as Partial<ItemFormData>
          }
          messageKey={scannedLabelData.message_key}
          onClose={() => {
            setShowQuickAdd(false);
            resumeCamera();
          }}
          onSuccess={() => {
            setShowQuickAdd(false);
            resumeCamera();
          }}
        />
      )}
      {showQuickActions && scannedLabelData?.item && (
        <QuickActionSheet
          item={scannedLabelData.item!}
          onClose={() => {
            setShowQuickActions(false);
            resumeCamera();
          }}
          onViewDetails={() => {
            setEditingItemId(scannedLabelData.item!.id);
            setShowQuickActions(false);
            setShowEditModal(true);
          }}
        />
      )}
      {showEditModal && editingItemId && (
        <ItemEditModal
          itemId={editingItemId}
          onClose={() => {
            setShowEditModal(false);
            resumeCamera();
          }}
        />
      )}
      {showArchivedInfo && scannedLabelData?.item && (
        <ArchivedItemSheet
          canWrite={canWrite}
          item={scannedLabelData.item!}
          labelCode={scannedLabelData.label_code}
          onClose={() => {
            setShowArchivedInfo(false);
            resumeCamera();
          }}
          onReuse={() => {
            setShowArchivedInfo(false);
            setShowQuickAdd(true);
          }}
        />
      )}
      <ScannedLocationSheet
        data={scannedLabelData}
        onClose={() => {
          setScannedLabelData(null);
          resumeCamera();
        }}
      />
      {showStockActions && scannedLabelData && (
        <StockActionSheet
          canWrite={canWrite}
          data={scannedLabelData}
          onClose={() => {
            setShowStockActions(false);
            resumeCamera();
          }}
          onConsume={handleStockConsume}
          onAddOne={handleStockAddOne}
          onUsePartially={partly}
          onAdd={handleStockAdd}
          onAddToShoppingList={
            canAddToShoppingList ? handleAddToShoppingList : undefined
          }
        />
      )}
    </div>
  );
}
