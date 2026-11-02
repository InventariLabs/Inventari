import { extractApiError } from "@/lib/errors";
import { useCallback, useState } from "react";
import { useDroppable } from "@dnd-kit/core";
import { Folder, FolderOpen, Pencil, Plus, Trash2 } from "lucide-react";
import type { TFunction } from "i18next";
import { toast } from "sonner";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/Button";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { Input } from "@/components/ui/Input";
import {
  Sheet,
  SheetActions,
  SheetBody,
  SheetTitle,
} from "@/components/ui/Sheet";
import {
  useCreateRecipeCollection,
  useDeleteRecipeCollection,
  useUpdateRecipeCollection,
} from "@/modules/recipes/hooks/useRecipes";
import type { RecipeCollection } from "@/modules/recipes/types/core";
import { DND_LABEL } from "@/lib/dndA11y";

/**
 * Shared collection CRUD state.
 *
 * The mobile chips row and the desktop sidebar used to be rendered as two
 * fragment siblings inside the page's flex row — with a collection present
 * the chips consumed the whole row on phones and the recipe grid collapsed
 * to ~6px. The two surfaces are now separate components; this hook owns the
 * create/rename/delete state they both drive, so the logic is not duplicated.
 */
export interface CollectionManager {
  modal: { mode: "create" | "rename"; collection?: RecipeCollection } | null;
  deleteTarget: RecipeCollection | null;
  name: string;
  openCreate: () => void;
  openRename: (collection: RecipeCollection) => void;
  handleSave: () => Promise<void>;
  handleDelete: () => Promise<void>;
  setDeleteTarget: (target: RecipeCollection | null) => void;
  setName: (name: string) => void;
  closeModal: () => void;
}

export function useCollectionManager(options: {
  t: TFunction;
  activeCollectionId: string | null;
  onSelect: (id: string | null) => void;
}): CollectionManager {
  const { t, activeCollectionId, onSelect } = options;
  const [modal, setModal] = useState<CollectionManager["modal"]>(null);
  const [name, setName] = useState("");
  const [deleteTarget, setDeleteTarget] = useState<RecipeCollection | null>(
    null,
  );

  const createMutation = useCreateRecipeCollection();
  const updateMutation = useUpdateRecipeCollection();
  const deleteMutation = useDeleteRecipeCollection();

  // Stable: the page header registers this as an action, and a fresh
  // function every render would re-register the whole header with it.
  const openCreate = useCallback(() => {
    setName("");
    setModal({ mode: "create" });
  }, []);

  const openRename = (collection: RecipeCollection) => {
    setName(collection.name);
    setModal({ mode: "rename", collection });
  };

  const handleSave = async () => {
    const trimmed = name.trim();
    if (!trimmed) return;
    try {
      if (modal?.mode === "create") {
        await createMutation.mutateAsync({ name: trimmed });
        toast.success(t("recipes:collections.created"));
      } else if (modal?.collection) {
        await updateMutation.mutateAsync({
          id: modal.collection.id,
          data: { name: trimmed },
        });
        toast.success(t("recipes:collections.updated"));
      }
      setModal(null);
    } catch (error) {
      toast.error(extractApiError(error, t("recipes:collections.error")));
    }
  };

  const handleDelete = async () => {
    if (!deleteTarget) return;
    try {
      await deleteMutation.mutateAsync(deleteTarget.id);
      if (activeCollectionId === deleteTarget.id) {
        onSelect(null);
      }
      toast.success(t("recipes:collections.deleted"));
      setDeleteTarget(null);
    } catch (error) {
      toast.error(extractApiError(error, t("recipes:collections.error")));
    }
  };

  return {
    modal,
    deleteTarget,
    name,
    openCreate,
    openRename,
    handleSave,
    handleDelete,
    setDeleteTarget,
    setName,
    closeModal: () => setModal(null),
  };
}

interface CollectionsChipsProps {
  collections: RecipeCollection[];
  activeCollectionId: string | null;
  onSelect: (id: string | null) => void;
  onOpenCreate: () => void;
  /** Whether to offer creating one — a collection is a record like any other. */
  canWrite?: boolean;
  t: TFunction;
}

/**
 * Mobile-only horizontal collection chips. Rendered ABOVE the page's
 * flex row by the parent — as a flex child next to the content column it
 * collapsed the grid to zero width on phones.
 */
export function CollectionsChips({
  collections,
  activeCollectionId,
  onSelect,
  onOpenCreate,
  canWrite = true,
  t,
}: CollectionsChipsProps) {
  // With zero collections there is nothing to filter by, and creating the
  // first one is a header action now — the same button on every screen width
  // rather than a dashed chip here and a ghost row in the sidebar.
  if (collections.length === 0) return null;
  return (
    <div
      className="md:hidden flex gap-1.5 overflow-x-auto pb-1 -mx-4 px-4"
      data-testid="collections-chips"
    >
      <Button
        size="content"
        type="button"
        variant="outline"
        onClick={() => onSelect(null)}
        className={cn(
          "shrink-0 rounded-full px-3 py-1 text-xs w-auto gap-0 bg-transparent",
          activeCollectionId === null
            ? "border-primary-500 bg-primary-50 hover:bg-primary-100 active:bg-primary-100 text-on font-medium"
            : "border-border text-on-secondary",
        )}
      >
        {t("recipes:collections.all_recipes")}
      </Button>
      {collections.map((collection) => (
        <Button
          size="content"
          key={collection.id}
          type="button"
          variant="outline"
          onClick={() => onSelect(collection.id)}
          className={cn(
            "shrink-0 rounded-full px-3 py-1 text-xs w-auto gap-0 bg-transparent",
            activeCollectionId === collection.id
              ? "border-primary-500 bg-primary-50 hover:bg-primary-100 active:bg-primary-100 text-on font-medium"
              : "border-border text-on-secondary",
          )}
        >
          {collection.icon && <span className="mr-1">{collection.icon}</span>}
          {collection.name}
        </Button>
      ))}
      {canWrite && (
        <Button
          size="content"
          type="button"
          variant="outline"
          onClick={onOpenCreate}
          className="shrink-0 rounded-full border-dashed px-3 py-1 text-xs w-auto gap-0 bg-transparent text-on-secondary"
        >
          + {t("recipes:collections.new_collection")}
        </Button>
      )}
    </div>
  );
}

interface CollectionsSidebarProps {
  collections: RecipeCollection[];
  activeCollectionId: string | null;
  isOverCollection: boolean;
  onSelect: (id: string | null) => void;
  manager: CollectionManager;
  /** Whether to offer renaming, deleting and creating collections. */
  canWrite?: boolean;
  t: TFunction;
}

/**
 * Desktop-only hierarchical collection tree. First child of the page's
 * flex row; nodes are droppable targets for recipe cards.
 */
export function CollectionsSidebar({
  collections,
  activeCollectionId,
  isOverCollection,
  onSelect,
  manager,
  canWrite = true,
  t,
}: CollectionsSidebarProps) {
  // With zero collections the 224px panel held "All recipes" (meaningless
  // without collections) and a lone "+ New collection" floating in
  // whitespace. Creating the first one is a header action now, so the panel
  // simply waits until there is something to list.
  if (collections.length === 0) return null;

  return (
    <div
      className="hidden md:block w-56 shrink-0 sticky top-20"
      data-testid="collections-sidebar"
    >
      <div className="flex flex-col gap-1">
        <Button
          size="content"
          type="button"
          variant="ghost"
          onClick={() => onSelect(null)}
          className={cn(
            "flex items-center gap-2 rounded-lg px-2.5 py-1.5 text-sm w-full justify-start font-normal",
            activeCollectionId === null
              ? "bg-surface-raised text-on font-medium"
              : "text-on-secondary hover:bg-surface-raised hover:text-on",
          )}
        >
          <FolderOpen size={16} className="text-on-muted" />
          <span className="truncate">
            {t("recipes:collections.all_recipes")}
          </span>
        </Button>

        <CollectionTree
          nodes={collections}
          depth={0}
          activeCollectionId={activeCollectionId}
          onSelect={onSelect}
          onRename={canWrite ? manager.openRename : undefined}
          onDelete={canWrite ? manager.setDeleteTarget : undefined}
          isOverCollection={isOverCollection}
          t={t}
        />

        {canWrite && (
          <Button
            size="content"
            type="button"
            variant="ghost"
            onClick={manager.openCreate}
            className="flex items-center gap-2 rounded-lg px-2.5 py-1.5 text-sm w-full justify-start font-normal text-on-secondary hover:bg-surface-raised hover:text-on"
          >
            <Plus size={16} className="text-on-muted" />
            <span>{t("recipes:collections.new_collection")}</span>
          </Button>
        )}
      </div>
    </div>
  );
}

/**
 * Shared create/rename/delete dialogs for both collection surfaces.
 * Rendered once at page level; the Sheet and ConfirmDialog escape their
 * parents visually, so they stay usable from the mobile chips and the
 * desktop tree alike.
 */
export function CollectionDialogs({
  manager,
  t,
}: {
  manager: CollectionManager;
  t: TFunction;
}) {
  return (
    <>
      <ConfirmDialog
        open={Boolean(manager.deleteTarget)}
        title={t("recipes:collections.delete")}
        message={t("recipes:collections.delete_confirm", {
          name: manager.deleteTarget?.name ?? "",
        })}
        variant="danger"
        confirmLabel={t("recipes:collections.delete")}
        cancelLabel={t("common:form.cancel")}
        onConfirm={manager.handleDelete}
        onCancel={() => manager.setDeleteTarget(null)}
      />

      {manager.modal && (
        <Sheet
          open
          onClose={manager.closeModal}
          zIndex="confirm"
          maxWidth="md"
          aria-label={
            manager.modal.mode === "create"
              ? t("recipes:collections.new_collection")
              : t("recipes:collections.rename")
          }
        >
          <SheetBody className="p-5">
            <SheetTitle className="text-sm mb-3">
              {manager.modal.mode === "create"
                ? t("recipes:collections.new_collection")
                : t("recipes:collections.rename")}
            </SheetTitle>
            <Input
              aria-label={t("recipes:collections.name_placeholder")}
              value={manager.name}
              onChange={(e) => manager.setName(e.target.value)}
              placeholder={t("recipes:collections.name_placeholder")}
              autoFocus
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  e.preventDefault();
                  void manager.handleSave();
                }
              }}
            />
            <SheetActions className="mt-5">
              <Button variant="outline" onClick={manager.closeModal}>
                {t("common:form.cancel")}
              </Button>
              <Button
                onClick={() => void manager.handleSave()}
                disabled={!manager.name.trim()}
              >
                {t("common:form.save")}
              </Button>
            </SheetActions>
          </SheetBody>
        </Sheet>
      )}
    </>
  );
}

interface CollectionTreeProps {
  nodes: RecipeCollection[];
  depth: number;
  activeCollectionId: string | null;
  onSelect: (id: string) => void;
  /** Absent for a reader: renaming and deleting are writes. */
  onRename?: (collection: RecipeCollection) => void;
  onDelete?: (collection: RecipeCollection) => void;
  isOverCollection: boolean;
  t: TFunction;
}

function CollectionTree({
  nodes,
  depth,
  activeCollectionId,
  onSelect,
  onRename,
  onDelete,
  isOverCollection,
  t,
}: CollectionTreeProps) {
  return (
    <>
      {nodes.map((collection) => (
        <CollectionNode
          key={collection.id}
          collection={collection}
          depth={depth}
          activeCollectionId={activeCollectionId}
          onSelect={onSelect}
          onRename={onRename}
          onDelete={onDelete}
          isOverCollection={isOverCollection}
          t={t}
        />
      ))}
    </>
  );
}

function CollectionNode({
  collection,
  depth,
  activeCollectionId,
  onSelect,
  onRename,
  onDelete,
  isOverCollection,
  t,
}: {
  collection: RecipeCollection;
  depth: number;
  activeCollectionId: string | null;
  onSelect: (id: string) => void;
  onRename?: (collection: RecipeCollection) => void;
  onDelete?: (collection: RecipeCollection) => void;
  isOverCollection: boolean;
  t: TFunction;
}) {
  const { setNodeRef, isOver } = useDroppable({
    id: `collection:${collection.id}`,
    data: {
      type: "collection",
      collectionId: collection.id,
      [DND_LABEL]: collection.name,
    },
  });

  const highlighted = isOver && isOverCollection;

  return (
    <>
      <div
        ref={setNodeRef}
        className={cn(
          "group flex items-center gap-2 rounded-lg px-2.5 py-1.5 text-sm transition-colors cursor-pointer",
          highlighted && "bg-primary-50 ring-1 ring-primary-400",
          activeCollectionId === collection.id
            ? "bg-surface-raised text-on font-medium"
            : "text-on-secondary hover:bg-surface-raised hover:text-on",
        )}
        style={{ marginLeft: depth * 14 }}
        onClick={() => onSelect(collection.id)}
        role="button"
        tabIndex={0}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            onSelect(collection.id);
          }
        }}
      >
        {collection.icon ? (
          <span className="text-sm leading-none">{collection.icon}</span>
        ) : (
          <Folder size={15} className="text-on-muted shrink-0" />
        )}
        <span className="truncate flex-1">{collection.name}</span>
        {collection.recipe_count > 0 && (
          <span className="text-xs text-on-muted tabular-nums">
            {collection.recipe_count}
          </span>
        )}
        <span className="flex items-center gap-0.5 shrink-0 transition-opacity md:opacity-0 md:group-hover:opacity-100 md:group-focus-within:opacity-100">
          {onRename && (
            <Button
              type="button"
              variant="ghost"
              size="inline"
              onClick={(e) => {
                e.stopPropagation();
                onRename(collection);
              }}
              aria-label={t("recipes:collections.rename")}
              title={t("recipes:collections.rename")}
              className="p-0.5 text-on-muted hover:text-primary-600"
            >
              <Pencil size={16} />
            </Button>
          )}
          {onDelete && (
            <Button
              type="button"
              variant="ghostDanger"
              size="inline"
              onClick={(e) => {
                e.stopPropagation();
                onDelete(collection);
              }}
              aria-label={t("recipes:collections.delete")}
              title={t("recipes:collections.delete")}
              className="p-0.5"
            >
              <Trash2 size={16} />
            </Button>
          )}
        </span>
      </div>
      {collection.children.length > 0 && (
        <CollectionTree
          nodes={collection.children}
          depth={depth + 1}
          activeCollectionId={activeCollectionId}
          onSelect={onSelect}
          onRename={onRename}
          onDelete={onDelete}
          isOverCollection={isOverCollection}
          t={t}
        />
      )}
    </>
  );
}

/** The collections read failed: the strip is missing, not empty. */
export function CollectionsLoadFailed({
  failed,
  onRetry,
  t,
}: {
  failed: boolean;
  onRetry: () => void;
  t: TFunction;
}) {
  if (!failed) return null;
  return (
    <div
      role="alert"
      className="mb-3 flex items-center gap-3 text-sm text-on-warning"
    >
      <span>{t("recipes:collections.load_failed")}</span>
      <Button variant="outline" size="sm" onClick={onRetry}>
        {t("common:actions.retry")}
      </Button>
    </div>
  );
}
