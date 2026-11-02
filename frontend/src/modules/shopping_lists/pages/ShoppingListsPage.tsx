import { useState, useEffect } from "react";
import { useTranslation } from "react-i18next";
import { extractApiError } from "@/lib/errors";
import { Plus, ShoppingCart } from "lucide-react";
import { useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { useModulePageHeader } from "@/hooks/useModulePageHeader";
import { useCanWrite } from "@/hooks/useCanWrite";
import { ReadOnlyNotice } from "@/components/ui/ReadOnlyNotice";
import { QueryFailure } from "@/components/ui/QueryResult";
import { Button } from "@/components/ui/Button";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { ListControlBar } from "@/components/ui/ListControlBar";
import { invalidation } from "@/lib/api/invalidation";
import CreateShoppingListModal from "../components/CreateShoppingListModal";
import { ShoppingListCard } from "../components/ShoppingListCard";
import {
  useShoppingLists,
  useShoppingListStats,
  useDeleteShoppingList,
  useUpdateShoppingList,
} from "../hooks/useShoppingLists";
import type { ShoppingList } from "@/modules/shopping_lists/types/shopping";

export default function ShoppingListsPage() {
  const { t } = useTranslation("shopping_lists");
  const { setHeader } = useModulePageHeader();
  const canWrite = useCanWrite("shopping_lists");
  const queryClient = useQueryClient();

  const [deleteListId, setDeleteListId] = useState<string | null>(null);
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [search, setSearch] = useState("");
  const [editingName, setEditingName] = useState<string | null>(null);
  const [newName, setNewName] = useState("");

  const {
    data: lists = [],
    isLoading,
    isError,
    error,
    refetch,
  } = useShoppingLists();
  const listStats = useShoppingListStats(lists);
  const deleteMutation = useDeleteShoppingList();
  const updateMutation = useUpdateShoppingList();

  useEffect(() => {
    setHeader({
      actions: canWrite ? (
        <div className="ml-auto">
          <Button
            onClick={() => setShowCreateModal(true)}
            leftIcon={<Plus size={16} />}
          >
            {t("newList")}
          </Button>
        </div>
      ) : undefined,
    });
  }, [t, setHeader, canWrite]);

  const handleCreateSuccess = () => {
    setShowCreateModal(false);
    invalidation.shoppingLists(queryClient);
  };

  const handleDelete = async () => {
    if (!deleteListId) return;
    try {
      await deleteMutation.mutateAsync(deleteListId);
      setDeleteListId(null);
      toast.success(t("messages.listDeleted"));
    } catch (error) {
      toast.error(extractApiError(error, t("messages.deleteError")));
    }
  };

  const startEditName = (list: ShoppingList) => {
    setEditingName(list.id);
    setNewName(list.name ?? "");
  };

  const handleSaveName = async (listId: string) => {
    try {
      await updateMutation.mutateAsync({ id: listId, name: newName });
      setEditingName(null);
      toast.success(t("messages.nameChanged"));
    } catch (error) {
      toast.error(extractApiError(error, t("messages.nameChangeError")));
    }
  };

  if (isError) {
    return (
      <QueryFailure
        error={error}
        message={extractApiError(error, t("common:errors.generic"))}
        onRetry={() => refetch()}
      />
    );
  }

  if (isLoading) {
    return (
      <div className="flex flex-col items-center justify-center h-96">
        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-accent-600 mb-4"></div>
        <p className="text-on-muted font-medium uppercase tracking-widest text-[10px]">
          {t("loading")}
        </p>
      </div>
    );
  }

  const filteredLists = lists.filter(
    (l) =>
      !search || (l.name ?? "").toLowerCase().includes(search.toLowerCase()),
  );

  return (
    <div className="space-y-6 animate-in fade-in slide-in-from-bottom-4 duration-700">
      <ReadOnlyNotice module="shopping_lists" />
      <ListControlBar
        search={{
          value: search,
          onChange: setSearch,
          placeholder: t("searchPlaceholder"),
        }}
        resultCount={search ? filteredLists.length : undefined}
      />
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
        {!Array.isArray(lists) || lists.length === 0 ? (
          <div className="col-span-full flex flex-col items-center justify-center py-16 text-center">
            <ShoppingCart size={48} className="text-on-muted/40 mb-4" />
            <h3 className="text-lg font-semibold text-on mb-1">
              {t("empty.title")}
            </h3>
            <p className="text-sm text-on-muted mb-6 max-w-md">
              {t("addFirst")}
            </p>
            {canWrite && (
              <Button
                onClick={() => setShowCreateModal(true)}
                leftIcon={<Plus size={16} />}
                // The header button's word (§14.4): both controls open the
                // same modal, so both carry the same name. "Create" stays the
                // modal's own submit button.
              >
                {t("newList")}
              </Button>
            )}
          </div>
        ) : (
          filteredLists.map((list) => {
            const stats = listStats[list.id] ?? {
              total: 0,
              purchased: 0,
              names: [],
            };

            return (
              <ShoppingListCard
                key={list.id}
                canWrite={canWrite}
                list={list}
                stats={stats}
                editingName={editingName}
                newName={newName}
                onSetNewName={setNewName}
                onStartEditName={() => startEditName(list)}
                onSaveName={() => handleSaveName(list.id)}
                to={`/shopping-lists/${list.id}`}
                onDeleteRequest={() => setDeleteListId(list.id)}
              />
            );
          })
        )}
      </div>

      {/* Delete Confirmation */}
      <ConfirmDialog
        open={deleteListId !== null}
        title={t("deleteModal.title")}
        message={t("deleteModal.desc")}
        variant="danger"
        confirmLabel={t("common:actions.delete")}
        cancelLabel={t("common:actions.cancel")}
        onConfirm={handleDelete}
        onCancel={() => setDeleteListId(null)}
      />

      {showCreateModal && (
        <CreateShoppingListModal
          onClose={() => setShowCreateModal(false)}
          onSuccess={handleCreateSuccess}
        />
      )}
    </div>
  );
}
