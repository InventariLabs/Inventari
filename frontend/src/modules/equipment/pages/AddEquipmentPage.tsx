import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useLocation, useParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import type { TFunction } from "i18next";
import { toast } from "sonner";
import { Layers3, Loader2, Monitor, Save } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { RecordNotFound } from "@/components/ui/RecordNotFound";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/Tabs";
import { useCanWrite } from "@/hooks/useCanWrite";
import { useModulePageHeader } from "@/hooks/useModulePageHeader";
import { useFormGuard } from "@/hooks/useFormGuard";
import { ReadOnlyNotice } from "@/components/ui/ReadOnlyNotice";
import { useScanCamera } from "@/hooks/useScanCamera";
import { useScanResolver } from "@/hooks/useScanResolver";
import { isNotFoundError } from "@/lib/errors";
import { isLabelCode, scanSubjectKind } from "@/lib/scan/scanSubject";
import QuickAddLocationModal from "@/modules/equipment/components/QuickAddLocationModal";
import BulkAddPanel from "@/modules/equipment/components/BulkAddPanel";
import { BatchLabelsSuccess } from "@/modules/equipment/components/BatchLabelsSuccess";
import EquipmentImageUpload from "@/modules/equipment/components/EquipmentImageUpload";
import { BasicInfoSection } from "@/modules/equipment/components/BasicInfoSection";
import { DynamicFieldsCard } from "@/modules/equipment/components/DynamicFieldsCard";
import { PurchaseNotesSection } from "@/modules/equipment/components/PurchaseNotesSection";
import { QueryError } from "@/components/ui/QueryResult";
import { ModelSelectCard } from "@/modules/equipment/components/ModelSelectCard";
import { useAllCategories } from "@/modules/shared/hooks/useCategories";
import { useEquipmentModels } from "@/modules/equipment/hooks/useEquipment";
import {
  useEquipmentForm,
  DEDICATED_KEYS,
} from "@/modules/equipment/hooks/useEquipmentForm";
import type { CategoryDTO, FieldDefinition, LabelScanView } from "@/types";
import LoadingSpinner from "@/components/LoadingSpinner";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/**
 * Renderable form fields: visible AND carrying a ``type``.
 *
 * The persisted ``category_id`` visibility flag
 * (``{'key': 'category_id', 'visible': True}``) has neither ``type`` nor
 * ``label``, yet the renderer drew every entry with ``visible !== false`` —
 * leaking an unlabelled ``category_id`` text input into the category card.
 * Runtime data is not guaranteed to satisfy the ``FieldDefinition`` shape,
 * so the ``type`` check is a truthiness guard against that persisted row.
 */
export function filterVisibleFields(
  fields: FieldDefinition[],
): FieldDefinition[] {
  return fields.filter((f) => f.visible !== false && f.type);
}

/** What the scan button beside Barcode / EAN made of a recognised code. */
export type BarcodeScanTarget =
  | { place: "barcode"; code: string; product: string | null }
  | { place: "label"; code: string }
  | { place: "elsewhere" };

/**
 * Where a recognised code goes when it was scanned into Barcode / EAN.
 *
 * The field records a manufacturer code; a label is not one, and its printed
 * QR carries a whole address (`{base}/s/{code}`) rather than the code. A
 * blank label belongs in the label field, where saving links the sticker to
 * the asset. A label already stuck to another product cannot be linked to
 * this one and is left to the resolver, which names that product and offers
 * a way to it — writing the address into either field is the bug this
 * function exists to stop. A recognised barcode stays in the field, carrying
 * the product it names so the reader can be told before saving that the code
 * already belongs to something.
 */
export function barcodeScanTarget(result: LabelScanView): BarcodeScanTarget {
  const kind = scanSubjectKind(result);
  if (kind === "storage" || kind === "document" || kind === "archived") {
    return { place: "elsewhere" };
  }
  // `show_quick_actions` is the label provider's answer for a sticker bound
  // to a live record; no barcode provider ever returns it.
  if (result.action === "show_quick_actions") {
    return { place: "elsewhere" };
  }
  const code = result.label_code;
  if (isLabelCode(code)) {
    return { place: "label", code };
  }
  return { place: "barcode", code, product: scannedProductName(result) };
}

/** The product a recognised code names, when the registry knows one. */
function scannedProductName(result: LabelScanView): string | null {
  return (
    result.message_params?.product ??
    result.stock_summary?.template?.name ??
    result.item?.name ??
    null
  );
}

/**
 * The resolver's `handle` for this page: applies a scan target to the form.
 *
 * Module-level so the page component stays inside its size gate; it needs
 * only the three calls it makes back into the page.
 */
function applyBarcodeScan(
  result: LabelScanView,
  deps: {
    setLabelCode: (code: string) => void;
    closeScanner: () => void;
    recordBarcode: (code: string) => boolean;
    t: TFunction;
  },
): boolean {
  const target = barcodeScanTarget(result);
  if (target.place === "elsewhere") return false;
  if (target.place === "label") {
    deps.setLabelCode(target.code);
    deps.closeScanner();
    toast(deps.t("scan:result.labelReady"));
    return true;
  }
  if (target.product) {
    toast(deps.t("scan:result.product", { product: target.product }));
  }
  return deps.recordBarcode(target.code);
}

export interface EquipmentFormData {
  name: string;
  category_id: string;
  location_id: string;
  barcode: string;
  label_code: string;
  purchase_price: string;
  purchase_date: string;
  warranty_until: string;
  notes: string;
  // Dynamic field values are heterogeneous (string, string[], boolean,
  // {amount, currency}). This is `unknown` so the
  // money / multi-select / boolean renderers can persist their typed
  // values without round-tripping through string.
  dynamic: Record<string, unknown>;
}

// Cancel ends this task, so it names where the task belongs — the asset
// being edited (where a save lands too), or the asset list — instead of
// popping the history stack: entered by address, from a scan or from another
// module, `navigate(-1)` left the reader wherever they happened to come from.
function cancelPath(editItemId: string | undefined): string {
  return editItemId ? `/equipment/${editItemId}` : "/equipment/assets";
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

/** What a scan hands over when it opens this page for a label it did not know. */
interface ScanPrefill {
  labelCode?: string;
  template?: {
    name?: string;
    brand?: string | null;
    location_id?: string | null;
    category_id?: string | null;
  };
}

export default function AddEquipmentPage() {
  const { t } = useTranslation(["equipment", "common"]);
  const navigate = useNavigate();
  const location = useLocation();

  const canWrite = useCanWrite("equipment");
  const { id: editItemId } = useParams<{ id?: string }>();
  const state = (location.state ?? {}) as ScanPrefill;

  const {
    form,
    set,
    setDynamic,
    fieldErrors,
    categoryRequired,
    handleModelSelect,
    handleSubmit,
    handleBulkSubmit,
    downloadBulkLabels,
    clearBulkLabelResult,
    isSubmitting,
    isBulkSubmitting,
    isFetchingItem,
    loadError,
    retryLoad,
    isDownloadingLabels,
    isEditMode,
    selectedModelId,
    currentImageUrl,
    bulkLabelResult,
    imageFile,
    setImageFile,
    deleteImageFlag,
    setDeleteImageFlag,
  } = useEquipmentForm(editItemId, state);
  const [showAddLocation, setShowAddLocation] = useState(false);
  const [mode, setMode] = useState<"single" | "batch">("single");
  const [scanOpen, setScanOpen] = useState(false);

  // The navigation gate: this page used to lose a filled form to
  // a click on the module tab, without a question. The pristine snapshot
  // freezes once the edit-mode read has settled — before that the form is
  // still filling itself, and nothing the reader typed exists yet.
  const pristineForm = useRef<EquipmentFormData | null>(null);
  if (pristineForm.current === null && !isFetchingItem) {
    pristineForm.current = form;
  }
  const isFormDirty = useMemo(() => {
    const pristine = pristineForm.current;
    if (pristine === null) return false;
    const keys = new Set([
      ...Object.keys(pristine),
      ...Object.keys(form),
    ] as (keyof EquipmentFormData)[]);
    for (const key of keys) {
      // Compared key by key, the way useItemForm does: a serialised whole
      // object would report every untouched form as edited when a key
      // changes order.
      if (JSON.stringify(pristine[key]) !== JSON.stringify(form[key])) {
        return true;
      }
    }
    return false;
  }, [form]);
  useFormGuard(isFormDirty, t("form.guardName", "The asset form"));

  const recordBarcode = useCallback(
    (code: string) => {
      set("barcode", code);
      setScanOpen(false);
      return true;
    },
    [set],
  );

  // The read goes through the shared registry, so a location or a document
  // scanned into the barcode field is named rather than written into it as if
  // it were a manufacturer code. A label QR carries a whole address: a blank
  // label's code moves to the label field, where saving links the sticker,
  // and a label already stuck to another product is named by the resolver
  // instead of being written anywhere. What is left — a product barcode, a
  // code no provider knows — is what this field is for; a barcode the
  // catalogue knows arrives with its product's name, said out loud before
  // the save can meet it.
  const { resolve } = useScanResolver({
    handle: (result) =>
      applyBarcodeScan(result, {
        setLabelCode: (code) => set("label_code", code),
        closeScanner: () => setScanOpen(false),
        recordBarcode,
        t,
      }),
    acceptUnrecognized: recordBarcode,
  });

  const {
    isCameraActive,
    scannerError,
    isTorchOn,
    toggleTorch,
    restartCamera,
  } = useScanCamera({ onCodeScanned: (code) => void resolve(code) });

  const { setHeader } = useModulePageHeader();
  useEffect(() => {
    setHeader({
      title: isEditMode
        ? t("form.editTitle", "Edit Asset")
        : t("form.addTitle", "Add Asset"),
      backTo: "/equipment",
      statusBadge: state.labelCode ? (
        <span className="text-xs font-mono text-on-secondary bg-surface-raised px-2 py-1 rounded">
          {state.labelCode}
        </span>
      ) : undefined,
    });
  }, [isEditMode, setHeader, state.labelCode, t]);

  const {
    data: allCategories = [],
    isError: categoriesFailed,
    refetch: refetchCategories,
  } = useAllCategories();
  const pickersFailed = categoriesFailed;
  const models = useEquipmentModels();

  const equipmentCategories = useMemo(
    () =>
      allCategories.filter((c: CategoryDTO) => c.context_tag === "equipment"),
    [allCategories],
  );

  const activeCategory = useMemo(
    () =>
      equipmentCategories.find((c: CategoryDTO) => c.id === form.category_id),
    [equipmentCategories, form.category_id],
  );

  // Purchase_date / warranty_until / notes are owned by
  // the dedicated cards — category-declared duplicates are dropped so the
  // form renders each field exactly once.
  const visibleFields = useMemo(
    // filters visible+typed fields via filterVisibleFields; drops
    // category-declared duplicates of the dedicated date/notes cards. Both
    // conditions must survive: taking either side silently kills the
    // other fix.
    () =>
      // The category's field definitions cross the wire as open dicts; the
      // entries are the shared FieldDefinition shape — narrowed once, here.
      filterVisibleFields(
        (activeCategory?.field_definitions ?? []) as FieldDefinition[],
      ).filter((f: FieldDefinition) => !DEDICATED_KEYS.has(f.key)),
    [activeCategory],
  );

  // The form is reachable by address, so hiding the buttons that lead here is
  // not the whole guard. A reader gets the same sentence the list gives them,
  // before filling anything in.
  if (!canWrite) {
    return (
      <div className="space-y-6">
        <ReadOnlyNotice module="equipment" />
      </div>
    );
  }

  if (isFetchingItem) {
    return (
      <div className="space-y-6">
        <LoadingSpinner />
      </div>
    );
  }

  // A form the read never filled is not an empty form — it is no form. Saving
  // it wrote the emptiness over the record, so there is nothing to render here
  // but the failure, and the way on from it.
  if (loadError) {
    return isNotFoundError(loadError) ? (
      <RecordNotFound
        title={t("detail.not_found")}
        backTo="/equipment"
        backLabel={t("list.back")}
      />
    ) : (
      <QueryError
        message={t("form.errors.loadFailed", "Failed to load asset")}
        onRetry={retryLoad}
      />
    );
  }

  if (bulkLabelResult) {
    return (
      <div className="space-y-6">
        <BatchLabelsSuccess
          count={bulkLabelResult.count}
          printTarget={{ labelIds: bulkLabelResult.labelIds }}
          printOptions={{ qrOnly: bulkLabelResult.qrOnly }}
          onDownload={downloadBulkLabels}
          isDownloading={isDownloadingLabels}
          onDone={() => {
            clearBulkLabelResult();
            navigate("/equipment/assets");
          }}
        />
      </div>
    );
  }

  // `replace` keeps the abandoned form out of Back.
  const handleCancel = () =>
    navigate(cancelPath(editItemId), { replace: true });

  return (
    <div className="space-y-6">
      {!isEditMode ? (
        <Tabs
          defaultValue="single"
          value={mode}
          onValueChange={(value) => setMode(value as "single" | "batch")}
          panels={false}
        >
          <TabsList className="w-full sm:w-fit">
            <TabsTrigger value="single" icon={<Monitor size={16} />}>
              {t("mode.single", "Single")}
            </TabsTrigger>
            <TabsTrigger value="batch" icon={<Layers3 size={16} />}>
              {t("mode.batch", "Batch")}
            </TabsTrigger>
          </TabsList>
        </Tabs>
      ) : null}

      <form
        noValidate
        onSubmit={(event) => {
          if (mode === "batch" && !isEditMode) {
            event.preventDefault();
            return;
          }
          handleSubmit(event);
        }}
        className="space-y-4"
      >
        {pickersFailed && (
          <QueryError
            message={t("form.pickersFailed")}
            onRetry={() => void refetchCategories()}
          />
        )}
        {!isEditMode && (
          <ModelSelectCard
            models={models.data ?? []}
            selectedModelId={selectedModelId}
            onSelect={handleModelSelect}
            error={models.error}
            onRetry={() => void models.refetch()}
          />
        )}

        <BasicInfoSection
          form={form}
          fieldErrors={fieldErrors}
          equipmentCategories={equipmentCategories}
          categoryRequired={categoryRequired}
          showLabelCode={isEditMode || mode === "single"}
          onSet={set}
          onShowAddLocation={() => setShowAddLocation(true)}
          scanOpen={scanOpen}
          scanLoading={false}
          isCameraActive={isCameraActive}
          scannerError={scannerError}
          isTorchOn={isTorchOn}
          onToggleScan={() => {
            const next = !scanOpen;
            setScanOpen(next);
            if (next) restartCamera();
          }}
          onToggleTorch={toggleTorch}
          onRetryScan={restartCamera}
        />

        {isEditMode || mode === "single" ? (
          <EquipmentImageUpload
            imageFile={imageFile}
            currentImageUrl={currentImageUrl}
            deleteImageFlag={deleteImageFlag}
            onImageFileSet={setImageFile}
            onDeleteImageFlagSet={setDeleteImageFlag}
          />
        ) : null}

        <DynamicFieldsCard
          visibleFields={visibleFields}
          activeCategory={activeCategory}
          formDynamic={form.dynamic}
          onSetDynamic={setDynamic}
          t={t}
        />

        <PurchaseNotesSection form={form} onSet={set} />

        {!isEditMode && mode === "batch" ? (
          <BulkAddPanel
            assetName={form.name}
            onSubmit={handleBulkSubmit}
            onCancel={handleCancel}
            isSubmitting={isBulkSubmitting}
          />
        ) : (
          <div className="flex items-center justify-end gap-2 pt-2 pb-8">
            <Button
              type="button"
              variant="outline"
              onClick={handleCancel}
              disabled={isSubmitting}
            >
              {t("common:form.cancel", "Cancel")}
            </Button>
            <Button type="submit" disabled={isSubmitting || pickersFailed}>
              {isSubmitting ? (
                <Loader2 size={16} className="animate-spin mr-2" />
              ) : (
                <Save size={16} className="mr-2" />
              )}
              {t("form.save", "Save Asset")}
            </Button>
          </div>
        )}
      </form>

      <QuickAddLocationModal
        isOpen={showAddLocation}
        onClose={() => setShowAddLocation(false)}
        onCreated={(id: string) => set("location_id", id)}
      />
    </div>
  );
}
