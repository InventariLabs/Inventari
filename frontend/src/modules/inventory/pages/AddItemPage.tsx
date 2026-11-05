import { useEffect, useState, useMemo } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { Camera, Edit } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { SheetActions, SheetFooter } from "@/components/ui/Sheet";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/Tabs";
import { QueryError } from "@/components/ui/QueryResult";
import { useQuickAdd } from "@/modules/inventory/hooks/useQuickAdd";
import { StorageRequired } from "@/modules/shared/components/StorageRequired";
import { NewLocationSheet } from "@/modules/shared/components/NewLocationSheet";
import { VisionTab } from "../components/quick-add/VisionTab";
import { ManualTab } from "../components/quick-add/ManualTab";
import { UnitChoiceDialog } from "../components/UnitChoiceDialog";
import CategoryCreateModal from "../components/CategoryCreateModal";
import { useModulePageHeader } from "@/hooks/useModulePageHeader";
import { useCanWrite } from "@/hooks/useCanWrite";
import { ReadOnlyNotice } from "@/components/ui/ReadOnlyNotice";

export default function AddItemPage() {
  const { t } = useTranslation(["items", "labels", "common"]);
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const { setHeader } = useModulePageHeader();
  const canWrite = useCanWrite("items");

  const [showNewCategoryForm, setShowNewCategoryForm] = useState(false);
  // The name typed into the location picker's search, when the reader asked
  // for a new location from there; `null` is the sheet closed.
  const [newStorageName, setNewStorageName] = useState<string | null>(null);

  // What this screen was asked for, and nothing more. What the scanner or the
  // previous product left behind is the form's business (`useQuickAdd`), which
  // is the only place that can still tell the two apart, say so on screen and
  // check that the place still exists: a place asked for is not checked.
  const initialStorageId = searchParams.get("location_id") || undefined;

  const contextTag = searchParams.get("context_tag") || undefined;

  const initialData = useMemo(() => {
    const name = searchParams.get("name");
    const barcode = searchParams.get("barcode");
    if (!name && !barcode) return undefined;
    return {
      name: name || "",
      barcode: barcode || "",
    };
  }, [searchParams]);

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
    carriedOver,
    clearCarriedOver,
    categories,
    categoriesFailure,
    assignMutation,
    handleFileSelect,
    handleImageSelect,
    isStoragesError,
    refetchStorages,
    pendingUnitChoice,
    resolveUnitChoice,
  } = useQuickAdd({
    initialStorageId,
    initialData,
    contextTag,
    onSuccess: () => navigate("/inventory/items"),
  });

  useEffect(() => {
    setHeader({ title: t("labels:quickAdd.title"), backTo: "/items" });
  }, [setHeader, t]);

  // The nav-leave guard for this form is armed inside `useQuickAdd` — the
  // hook both this page and QuickAddModal share. Registering here too would
  // make the last-mounted writer win the guard's single slot.

  const handleSubmit = async (e?: React.FormEvent) => {
    if (e) e.preventDefault();
    await submit(e);
  };

  // The storage field's own way out when the picker has nothing to offer —
  // an empty list used to cost the whole form. Built here rather than in the
  // form body: StorageRequired belongs to the spaces module, and this page
  // is the composition root the boundary baseline already knows.
  const storageGate =
    noStorages === true ? (
      <StorageRequired
        variant="field"
        purpose="stock"
        onCreated={(storage) => handleInputChange("location_id", storage.id)}
      />
    ) : undefined;

  // The list that leads here asks first, so an account without the right
  // never sees the button. Typing the address, or following an old link,
  // used to open the whole form anyway — filled in, submitted, and refused
  // by a 403 at the end of the work.
  if (!canWrite) {
    return (
      <div className="p-6 sm:max-w-6xl sm:mx-auto">
        <ReadOnlyNotice module="items" />
      </div>
    );
  }

  // The page flows and scrolls with the shell, and the footer sticks to the
  // bottom of the viewport. A fixed height written as "viewport minus some
  // rem" had to guess how tall the chrome above it is, and guessed short: at
  // 1440x1000 the form ended 170px below the fold, with the submit button out
  // of reach until the page was scrolled.
  return (
    <div className="flex flex-col bg-surface-card sm:max-w-6xl sm:mx-auto sm:my-4 sm:rounded-2xl sm:shadow-md animate-in fade-in slide-in-from-bottom duration-300">
      {/* The list never arrived. Without this branch the form rendered whole,
          with a required "Storage location" that had nothing to pick and no
          word about why — the reader filled the rest in and found out at save
          time. An empty-but-loaded list is a different case: the form stays,
          and the field itself carries the way out (the field variant of
          StorageRequired, under the picker). */}
      {isStoragesError ? (
        <div className="flex-1 flex flex-col items-center justify-center p-8">
          <QueryError onRetry={refetchStorages} />
        </div>
      ) : (
        <>
          {/* Mode Tabs — only where reading a photo is a thing this
              installation can do; `vision` is a module and can be off. */}
          {visionEnabled && (
            <div className="px-6 pt-5 flex-shrink-0">
              <Tabs
                defaultValue={activeTab}
                value={activeTab}
                onValueChange={(v) => setActiveTab(v as "vision" | "manual")}
                panels={false}
              >
                <TabsList className="w-full">
                  <TabsTrigger value="vision" icon={<Camera size={16} />}>
                    {t("labels:quickAdd.tabVision")}
                  </TabsTrigger>
                  <TabsTrigger value="manual" icon={<Edit size={16} />}>
                    {t("labels:quickAdd.tabManual")}
                  </TabsTrigger>
                </TabsList>
              </Tabs>
            </div>
          )}

          <div className="flex-1 p-6">
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
                errors={errors}
                fieldDefinitions={fieldDefinitions}
                handleSubmit={handleSubmit}
                categories={categories}
                categoriesFailure={categoriesFailure}
                onAddCategory={() => setShowNewCategoryForm(true)}
                imagePreview={imagePreview}
                setImagePreview={setImagePreview}
                onImageSelect={handleImageSelect}
                carriedOver={carriedOver}
                onClearCarriedOver={clearCarriedOver}
                storageGate={storageGate}
                onAddStorage={setNewStorageName}
              />
            )}
          </div>

          {/* Footer — on a phone it sticks above the bottom navigation, which
              is fixed and would otherwise cover it. */}
          <SheetFooter className="sticky bottom-[calc(var(--mobile-nav-height)+env(safe-area-inset-bottom,0px))] md:bottom-0 z-[var(--z-sticky)] pb-3 sm:rounded-b-2xl">
            <SheetActions>
              {/* Cancel ends this task, so it names the list it belongs to
                  rather than popping the history stack: entered by address
                  or from another module, `navigate(-1)` used to leave the
                  reader wherever they happened to come from. */}
              <Button
                variant="outline"
                onClick={() => navigate("/inventory/items", { replace: true })}
              >
                {t("common:actions.cancel")}
              </Button>
              <Button
                type="submit"
                form="quick-add-form"
                disabled={
                  activeTab === "vision" ||
                  assignMutation.isPending ||
                  !formData.name ||
                  !formData.location_id
                }
                isLoading={assignMutation.isPending}
              >
                {t("labels:quickAdd.submit")}
              </Button>
            </SheetActions>
          </SheetFooter>

          <NewLocationSheet
            open={newStorageName !== null}
            initialName={newStorageName ?? ""}
            onClose={() => setNewStorageName(null)}
            onCreated={(storage) =>
              handleInputChange("location_id", storage.id)
            }
          />

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

          {/* The unit the matched template does not keep waits here too: the
              save is held until somebody answers, and on this screen nothing
              else can ask. Without this the button was simply dead. */}
          {pendingUnitChoice && (
            <UnitChoiceDialog
              choice={pendingUnitChoice}
              onResolve={resolveUnitChoice}
            />
          )}
        </>
      )}
    </div>
  );
}
