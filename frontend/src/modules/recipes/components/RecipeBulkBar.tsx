import { useState } from "react";
import { CheckSquare, FolderPlus, Tag, X } from "lucide-react";
import type { TFunction } from "i18next";
import { Button } from "@/components/ui/Button";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { Input } from "@/components/ui/Input";
import {
  Sheet,
  SheetActions,
  SheetBody,
  SheetFooter,
  SheetTitle,
} from "@/components/ui/Sheet";
import type { RecipeCollection } from "@/modules/recipes/types/core";

interface RecipeBulkBarProps {
  open: boolean;
  selectedCount: number;
  /** True when every recipe on the current page is selected. */
  allSelected: boolean;
  isBusy: boolean;
  collections: RecipeCollection[];
  onSelectAll: () => void;
  onTag: (tags: string[]) => void;
  onDelete: () => void;
  onAddToCollection: (collectionId: string) => Promise<void>;
  onClear: () => void;
  t: TFunction;
}

/**
 * RecipeBulkBar — floating action bar for multi-select mode.
 *
 * Shows the selected count plus Select all / Tag / Add to collection /
 * Delete / Clear actions. The tag modal (bottom sheet on mobile,
 * centered on desktop), the collection picker and the delete confirmation
 * all live here with the bar.
 */
export function RecipeBulkBar({
  open,
  selectedCount,
  allSelected,
  isBusy,
  collections,
  onSelectAll,
  onTag,
  onDelete,
  onAddToCollection,
  onClear,
  t,
}: RecipeBulkBarProps) {
  const [tagModalOpen, setTagModalOpen] = useState(false);
  const [tagInput, setTagInput] = useState("");
  const [deleteConfirmOpen, setDeleteConfirmOpen] = useState(false);
  const [collectionPickerOpen, setCollectionPickerOpen] = useState(false);
  const [pickedCollectionId, setPickedCollectionId] = useState<string | null>(
    null,
  );

  if (!open) return null;

  const applyTags = () => {
    const tags = tagInput
      .split(",")
      .map((tag) => tag.trim().toLowerCase())
      .filter(Boolean);
    if (tags.length === 0) return;
    onTag(tags);
    setTagInput("");
    setTagModalOpen(false);
  };

  const applyAddToCollection = async () => {
    if (!pickedCollectionId) return;
    try {
      await onAddToCollection(pickedCollectionId);
      setPickedCollectionId(null);
      setCollectionPickerOpen(false);
    } catch {
      // toast handled by the parent
    }
  };

  return (
    <>
      <div className="fixed bottom-0 left-0 right-0 z-[var(--z-modal)] px-4 pb-[max(1rem,env(safe-area-inset-bottom))]">
        <div
          role="toolbar"
          aria-label={t("recipes:bulk.toolbar_label", { count: selectedCount })}
          className="flex flex-wrap items-center justify-center gap-2 rounded-2xl border border-border bg-surface-card px-4 py-2.5 shadow-lg max-w-lg mx-auto"
        >
          <span className="text-sm text-on-secondary whitespace-nowrap">
            {t("recipes:bulk.selected_count", { count: selectedCount })}
          </span>
          <Button
            variant="outline"
            size="sm"
            onClick={onSelectAll}
            disabled={selectedCount === 0 && allSelected}
            leftIcon={<CheckSquare size={16} />}
          >
            {allSelected
              ? t("recipes:bulk.deselect_all")
              : t("recipes:bulk.select_all")}
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={() => setTagModalOpen(true)}
            disabled={selectedCount === 0}
            leftIcon={<Tag size={16} />}
          >
            {t("recipes:bulk.tag_selected")}
          </Button>
          {collections.length > 0 && (
            <Button
              variant="outline"
              size="sm"
              onClick={() => {
                setPickedCollectionId(null);
                setCollectionPickerOpen(true);
              }}
              disabled={selectedCount === 0}
              leftIcon={<FolderPlus size={16} />}
            >
              {t("recipes:bulk.add_to_collection")}
            </Button>
          )}
          <Button
            variant="outline"
            size="sm"
            onClick={() => setDeleteConfirmOpen(true)}
            disabled={selectedCount === 0}
            className="text-red-600 hover:text-red-700"
          >
            {t("recipes:bulk.delete_selected")}
          </Button>
          <Button
            variant="ghost"
            size="icon"
            onClick={onClear}
            aria-label={t("recipes:bulk.clear")}
            title={t("recipes:bulk.clear")}
          >
            <X size={16} />
          </Button>
        </div>
      </div>

      <ConfirmDialog
        open={deleteConfirmOpen}
        title={t("recipes:bulk.delete_selected")}
        message={t("recipes:bulk.delete_confirm", { count: selectedCount })}
        variant="danger"
        confirmLabel={t("recipes:actions.delete")}
        cancelLabel={t("common:form.cancel")}
        onConfirm={() => {
          onDelete();
          setDeleteConfirmOpen(false);
        }}
        onCancel={() => setDeleteConfirmOpen(false)}
      />

      {collectionPickerOpen && (
        <Sheet
          open
          onClose={() => setCollectionPickerOpen(false)}
          zIndex="confirm"
          maxWidth="md"
          aria-label={t("recipes:bulk.collection_title")}
        >
          <SheetBody className="p-5">
            <SheetTitle className="text-sm mb-1">
              {t("recipes:bulk.collection_title")}
            </SheetTitle>
            <p className="text-xs text-on-secondary mb-3">
              {t("recipes:bulk.pick_collection")}
            </p>
            <div className="space-y-1 max-h-64 overflow-y-auto">
              {collections.map((collection) => (
                <Button
                  key={collection.id}
                  type="button"
                  variant="ghost"
                  onClick={() => setPickedCollectionId(collection.id)}
                  // `active:scale-100` on purpose: picking one of
                  // these rows marks it, and the mark is the feedback. A 2%
                  // shrink of a full-width row on top of that reads as a
                  // wobble in the list.
                  className={`w-full flex items-center gap-2 rounded-xl border px-3 py-2.5 text-sm justify-start font-normal active:scale-100 ${
                    pickedCollectionId === collection.id
                      ? "border-primary-500 bg-primary-50 text-on font-semibold"
                      : "border-border text-on hover:bg-surface"
                  }`}
                >
                  {collection.icon && <span>{collection.icon}</span>}
                  <span className="truncate">{collection.name}</span>
                </Button>
              ))}
            </div>
          </SheetBody>
          <SheetFooter>
            <SheetActions>
              <Button
                variant="outline"
                onClick={() => setCollectionPickerOpen(false)}
              >
                {t("common:form.cancel")}
              </Button>
              <Button
                onClick={() => void applyAddToCollection()}
                disabled={isBusy || !pickedCollectionId}
              >
                {t("recipes:bulk.add")}
              </Button>
            </SheetActions>
          </SheetFooter>
        </Sheet>
      )}

      {tagModalOpen && (
        <Sheet
          open
          onClose={() => setTagModalOpen(false)}
          zIndex="confirm"
          maxWidth="md"
          aria-label={t("recipes:bulk.tag_title", { count: selectedCount })}
        >
          <SheetBody className="p-5">
            <SheetTitle className="text-sm mb-1">
              {t("recipes:bulk.tag_title", { count: selectedCount })}
            </SheetTitle>
            <p className="text-xs text-on-secondary mb-3">
              {t("recipes:bulk.tag_hint")}
            </p>
            <Input
              aria-label={t("recipes:bulk.tag_placeholder")}
              value={tagInput}
              onChange={(e) => setTagInput(e.target.value)}
              placeholder={t("recipes:bulk.tag_placeholder")}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  e.preventDefault();
                  applyTags();
                }
              }}
            />
          </SheetBody>
          <SheetFooter>
            <SheetActions>
              <Button variant="outline" onClick={() => setTagModalOpen(false)}>
                {t("common:form.cancel")}
              </Button>
              <Button onClick={applyTags} disabled={isBusy || !tagInput.trim()}>
                {t("recipes:bulk.apply")}
              </Button>
            </SheetActions>
          </SheetFooter>
        </Sheet>
      )}
    </>
  );
}
