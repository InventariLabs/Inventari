import { useState } from "react";
import { X, Camera, Edit, Loader2, MapPin } from "lucide-react";
import { useTranslation } from "react-i18next";
import { useQuickAdd } from "@/modules/inventory/hooks/useQuickAdd";
import { VisionTab } from "./quick-add/VisionTab";
import { ManualTab } from "./quick-add/ManualTab";
import CategoryCreateModal from "./CategoryCreateModal";
import { Button } from "@/components/ui/Button";
import { Sheet, SheetActions, SheetFooter } from "@/components/ui/Sheet";
import type { Item } from "@/types";
import type { ItemFormData } from "@/modules/inventory/hooks/useItemForm";
import { UnitChoiceDialog } from "./UnitChoiceDialog";
import { AttachLabelToItemSheet } from "./AttachLabelToItemSheet";
import { isLabelCode } from "@/lib/scan/scanSubject";

interface Props {
  labelCode?: string;
  initialStorageId?: string;
  initialData?: Partial<ItemFormData>;
  /**
   * What the scan said about the code, as the catalogue key the server sends.
   * The difference between a brand-new product, one matched from history and
   * a free pool label used to be read out of the English sentence
   * (`message.includes("history")`), which made the sentence load-bearing:
   * translating it would have switched the "matched from your previous
   * products" answer off in silence. The key is the contract; the sentence is
   * free to be a sentence.
   */
  messageKey?: string | null;
  onClose: () => void;
  onSuccess: (newItem?: Item) => void;
}

export default function QuickAddModal({
  labelCode,
  initialStorageId,
  initialData,
  messageKey,
  onClose,
  onSuccess,
}: Props) {
  const { t } = useTranslation([
    "labels",
    "items",
    "common",
    "categories",
    "locations",
  ]);
  const {
    activeTab,
    setActiveTab,
    visionEnabled,
    formData,
    errors,
    fieldDefinitions,
    handleInputChange,
    submit,
    isAnalyzing,
    imagePreview,
    setImagePreview,
    handleVisionAI,
    noStorages,
    hasHiddenStorages,
    carriedOver,
    clearCarriedOver,
    categories,
    categoriesFailure,
    templateUnit,
    pendingUnitChoice,
    resolveUnitChoice,
    assignMutation,
    handleFileSelect,
    handleImageSelect,
  } = useQuickAdd({
    labelCode,
    initialStorageId,
    initialData,
    onSuccess: (newItem) => {
      onSuccess(newItem);
      onClose();
    },
  });

  const [showNewCategoryForm, setShowNewCategoryForm] = useState(false);
  const [attaching, setAttaching] = useState(false);
  const isFromHistory = messageKey === "scan:result.foundInHistory";
  // A free pool label can name a product that already exists; a scanned
  // barcode is not a label and has nothing to bind.
  const canAttachToExisting =
    Boolean(labelCode) && messageKey === "scan:result.labelReady";

  // A scanned barcode is the product's code, shown in the header and saved
  // with the product; the form does not ask for it again. A pool label is
  // no product code, so after one the field stays.
  const formFields =
    labelCode && !isLabelCode(labelCode)
      ? fieldDefinitions.filter((f) => f.key !== "barcode")
      : fieldDefinitions;

  const handleManualSubmit = async (e?: React.FormEvent) => {
    if (e) e.preventDefault();
    await submit(e);
  };

  return (
    <Sheet
      open
      onClose={onClose}
      maxWidth="6xl"
      zIndex="confirm"
      aria-label={t("quickAdd.title")}
    >
      {/* Header */}
      <div className="p-6 border-b flex-shrink-0">
        <div className="flex items-center justify-between mb-4">
          <div>
            <h3 className="text-xl font-semibold text-on">
              {t("quickAdd.title")}
            </h3>
            {labelCode && (
              <p className="text-xs text-on-secondary flex items-center gap-1 mt-1">
                {/* Named neutrally on purpose: this is a printed label's
                    short code when a label was scanned and a product's own
                    barcode when the reader scanned the packaging. Calling
                    it "Label code" was right half the time. */}
                {t("quickAdd.scannedCode")}:{" "}
                <span className="font-mono font-bold px-1.5 py-0.5 rounded text-primary-600 bg-primary-50">
                  {labelCode}
                </span>
              </p>
            )}
          </div>
          <Button
            onClick={onClose}
            variant="ghost"
            size="icon"
            className="rounded-full text-on-muted"
            aria-label={t("common:actions.close")}
          >
            <X size={24} />
          </Button>
        </div>
      </div>

      {/* After the header, so the close button — not this one — is what the
          sheet's focus lands on first. */}
      {canAttachToExisting && (
        <div className="px-6 pt-3 flex-shrink-0">
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => setAttaching(true)}
          >
            {t("labels:attachToItem.title")}
          </Button>
        </div>
      )}

      {/* No storages guard */}
      {noStorages === true ? (
        <div className="flex-1 flex flex-col items-center justify-center p-8 text-center gap-4">
          <div className="w-16 h-16 rounded-2xl bg-amber-50 flex items-center justify-center">
            <MapPin size={32} className="text-amber-500" />
          </div>
          <div>
            <p className="font-semibold text-on text-lg">
              {hasHiddenStorages
                ? t("locations:hidden.title")
                : t("quickAdd.noLocations")}
            </p>
            <p className="text-on-secondary text-sm mt-1">
              {hasHiddenStorages
                ? t("locations:hidden.description")
                : t("quickAdd.noLocationsHint")}
            </p>
          </div>
          <Button
            // open the settings in a new tab so the user doesn't
            // lose this modal / form state when configuring a location.
            onClick={() =>
              window.open(
                hasHiddenStorages
                  ? "/settings#module-data"
                  : "/inventory/locations",
                "_blank",
                "noopener",
              )
            }
            size="lg"
          >
            {hasHiddenStorages
              ? t("locations:hidden.openSettings")
              : t("quickAdd.configureStorages")}
          </Button>
        </div>
      ) : (
        <>
          {/* Mode Tabs — hidden when product data already known (e.g. re-adding from stock) */}
          {!initialData && visionEnabled && (
            <div className="px-6 pt-4 flex-shrink-0">
              <div className="flex bg-surface-raised p-1 rounded-xl">
                <Button
                  type="button"
                  onClick={() => setActiveTab("vision")}
                  variant="ghost"
                  size="contentSm"
                  className={`min-h-11 md:min-h-0 min-w-11 md:min-w-0 flex-1 font-semibold text-sm ${activeTab === "vision" ? "bg-surface-card text-primary-600 shadow-sm" : "text-on-secondary hover:text-on"}`}
                >
                  <Camera size={16} />
                  {t("quickAdd.tabVision")}
                </Button>
                <Button
                  type="button"
                  onClick={() => setActiveTab("manual")}
                  variant="ghost"
                  size="contentSm"
                  className={`min-h-11 md:min-h-0 min-w-11 md:min-w-0 flex-1 font-semibold text-sm ${activeTab === "manual" ? "bg-surface-card text-primary-600 shadow-sm" : "text-on-secondary hover:text-on"}`}
                >
                  <Edit size={16} />
                  {t("quickAdd.tabManual")}
                </Button>
              </div>
            </div>
          )}

          <div className="flex-1 min-h-0 p-6 pb-6 overflow-y-auto custom-scrollbar">
            {activeTab === "vision" ? (
              <VisionTab
                onAnalyze={handleVisionAI}
                onEnterManually={() => setActiveTab("manual")}
                isAnalyzing={isAnalyzing}
              />
            ) : (
              <ManualTab
                formData={formData}
                onChange={handleInputChange}
                onFileSelect={handleFileSelect}
                onImageSelect={handleImageSelect}
                errors={errors}
                fieldDefinitions={formFields}
                handleSubmit={submit}
                isFromHistory={isFromHistory}
                categories={categories}
                categoriesFailure={categoriesFailure}
                onAddCategory={() => setShowNewCategoryForm(true)}
                imagePreview={imagePreview}
                setImagePreview={setImagePreview}
                carriedOver={carriedOver}
                onClearCarriedOver={clearCarriedOver}
                templateUnit={templateUnit}
              />
            )}
          </div>

          {/* Footer */}
          <SheetFooter>
            <SheetActions>
              <Button type="button" variant="outline" onClick={onClose}>
                {t("common:actions.cancel")}
              </Button>
              <Button
                onClick={handleManualSubmit}
                disabled={
                  activeTab === "vision" ||
                  assignMutation.isPending ||
                  !formData.name ||
                  !formData.location_id
                }
              >
                {assignMutation.isPending ? (
                  <Loader2 size={20} className="animate-spin" />
                ) : (
                  t("quickAdd.submit")
                )}
              </Button>
            </SheetActions>
          </SheetFooter>
        </>
      )}

      {attaching && labelCode && (
        <AttachLabelToItemSheet
          labelCode={labelCode}
          onClose={() => setAttaching(false)}
          onAttached={onClose}
        />
      )}

      {/* Category Modal */}
      {showNewCategoryForm && (
        <CategoryCreateModal
          onClose={() => setShowNewCategoryForm(false)}
          onSuccess={(newCat) => {
            setShowNewCategoryForm(false);
            handleInputChange("category_id", newCat.id);
          }}
        />
      )}

      {/* The unit the product is counted in, if the reader picked another */}
      {pendingUnitChoice && (
        <UnitChoiceDialog
          choice={pendingUnitChoice}
          onResolve={resolveUnitChoice}
        />
      )}
    </Sheet>
  );
}
