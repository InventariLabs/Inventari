import { useState, useEffect } from "react";
import { useParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { extractApiError, isNotFoundError } from "@/lib/errors";
import { QueryError } from "@/components/ui/QueryResult";
import { RecordNotFound } from "@/components/ui/RecordNotFound";
import { Plus, Trash2, ShoppingCart, BookOpen } from "lucide-react";
import { useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { TypedSlot } from "@/components/Slot";
import { useOrganizationCurrency } from "@/hooks/useOrganizationCurrency";
import { useConfirm } from "@/hooks/useConfirm";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import Button from "@/components/ui/Button";
import { useModulePageHeader } from "@/hooks/useModulePageHeader";
import { useCanWrite } from "@/hooks/useCanWrite";
import { ReadOnlyNotice } from "@/components/ui/ReadOnlyNotice";
import { ShoppingListItemCard } from "../components/ShoppingListItemCard";
import { useModules } from "@/contexts/ModulesContext";
import AddFromRecipesModal from "../components/AddFromRecipesModal";
import { invalidation } from "@/lib/api/invalidation";
import {
  useShoppingListDetail,
  useToggleShoppingItem,
  useClearPurchasedItems,
  useDeleteShoppingItem,
  useConvertToPO,
} from "../hooks/useShoppingLists";

export default function ShoppingListDetailPage() {
  const { t } = useTranslation("shopping_lists");
  const currency = useOrganizationCurrency();
  const { id } = useParams<{ id: string }>();
  const { confirm, confirmDialogProps } = useConfirm();
  const [showAddModal, setShowAddModal] = useState(false);
  const [showRecipesModal, setShowRecipesModal] = useState(false);
  const { setHeader } = useModulePageHeader();
  const canWrite = useCanWrite("shopping_lists");
  const { isModuleEnabled } = useModules();
  const recipesEnabled = isModuleEnabled("recipes");
  const poEnabled = isModuleEnabled("purchase_orders");
  const queryClient = useQueryClient();

  const { data: list, isLoading, error, refetch } = useShoppingListDetail(id);
  const toggleMutation = useToggleShoppingItem(id!);
  const clearMutation = useClearPurchasedItems(id!);
  const deleteItemMutation = useDeleteShoppingItem(id!);
  const convertMutation = useConvertToPO(id!);

  useEffect(() => {
    if (!list) return;
    const pending = list.items?.filter((i) => !i.is_purchased) || [];
    const purchased = list.items?.filter((i) => i.is_purchased) || [];
    setHeader({
      title: list.name ?? undefined,
      subtitle: `${t("detail.toBuyCount", { count: pending.length })} · ${t("detail.purchasedCount", { count: purchased.length })}`,
      backTo: "/shopping-lists",
      actions: canWrite ? (
        <div className="flex gap-2">
          {recipesEnabled && (
            <Button
              variant="outline"
              onClick={() => setShowRecipesModal(true)}
              leftIcon={<BookOpen size={16} />}
            >
              {t("addFromRecipes.title")}
            </Button>
          )}
          <Button
            onClick={() => setShowAddModal(true)}
            leftIcon={<Plus size={16} />}
          >
            {t("common:actions.add", { defaultValue: "Product" })}
          </Button>
        </div>
      ) : undefined,
    });
  }, [list, setHeader, t, recipesEnabled, canWrite]);

  const handleTogglePurchased = async (
    itemId: string,
    currentStatus: boolean,
  ) => {
    try {
      await toggleMutation.mutateAsync({ itemId, currentStatus });
    } catch (error) {
      toast.error(extractApiError(error, t("detail.errorUpdateItem")));
    }
  };

  const handleClearPurchased = async () => {
    if (!id) return;
    if (
      !(await confirm({
        title: t("detail.clearPurchased", {
          count: purchasedItems.length,
          defaultValue: "Clear purchased",
        }),
        message: t("detail.confirmClearPurchased"),
        variant: "danger",
      }))
    )
      return;
    try {
      await clearMutation.mutateAsync();
      toast.success(t("detail.successClearPurchased"));
    } catch (error) {
      toast.error(
        extractApiError(
          error,
          t("detail.errorClearPurchased", {
            defaultValue: "Failed to clear list",
          }),
        ),
      );
    }
  };

  const handleDeleteItem = async (itemId: string) => {
    if (!id) return;
    if (
      !(await confirm({
        title: t("common:actions.delete"),
        message: t("detail.confirmDeleteItem"),
        variant: "danger",
      }))
    )
      return;
    try {
      await deleteItemMutation.mutateAsync(itemId);
      toast.success(t("detail.successDeleteItem"));
    } catch (error) {
      toast.error(extractApiError(error, t("detail.errorDeleteItem")));
    }
  };

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary-600"></div>
      </div>
    );
  }

  // A list that was deleted is not a failed request, and the reader can act on
  // only one of the two.
  if (error && !isNotFoundError(error)) {
    return <QueryError onRetry={() => void refetch()} />;
  }

  if (!list) {
    return (
      <RecordNotFound
        title={t("detail.listNotFound")}
        backTo="/shopping-lists"
        backLabel={t("detail.backToLists")}
      />
    );
  }

  const pendingItems = (list.items?.filter((i) => !i.is_purchased) || []).sort(
    (a, b) => (b.priority || 0) - (a.priority || 0),
  );
  const purchasedItems = list.items?.filter((i) => i.is_purchased) || [];
  const convertibleCount = pendingItems.filter((i) => i.template_id).length;
  const poSkippedCount = pendingItems.length - convertibleCount;

  const handleConvertToPO = async () => {
    if (!id) return;
    if (
      !(await confirm({
        title: t("detail.convertToPo", {
          defaultValue: "Convert to Purchase Order",
        }),
        message: [
          t("detail.confirmConvertGrouped", { count: convertibleCount }),
          t("detail.confirmConvertSkipped", { count: poSkippedCount }),
        ].join(" "),
      }))
    )
      return;
    try {
      const result = await convertMutation.mutateAsync(undefined);
      toast.success(
        t("detail.convertToPoSuccess", {
          number: result.po_number,
          defaultValue: `Purchase order ${result.po_number} created`,
        }),
      );
    } catch (error) {
      toast.error(
        extractApiError(
          error,
          t("detail.convertToPoError", {
            defaultValue: "Failed to create purchase order",
          }),
        ),
      );
    }
  };

  return (
    <div className="space-y-6">
      <ReadOnlyNotice module="shopping_lists" />
      {poEnabled && convertibleCount > 0 && canWrite && (
        <div className="flex justify-end">
          <Button
            variant="outline"
            size="sm"
            onClick={handleConvertToPO}
            disabled={convertMutation.isPending}
            leftIcon={<ShoppingCart size={14} />}
          >
            {t("detail.convertToPo", {
              defaultValue: "Convert to Purchase Order",
            })}
          </Button>
        </div>
      )}
      {purchasedItems.length > 0 && canWrite && (
        <div className="flex justify-end">
          <Button
            variant="ghost"
            size="sm"
            onClick={handleClearPurchased}
            className="text-red-600 hover:bg-red-50"
          >
            <Trash2 size={14} />
            {t("detail.clearPurchased", {
              count: purchasedItems.length,
              defaultValue: `Clear purchased (${purchasedItems.length})`,
            })}
          </Button>
        </div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
        {pendingItems.map((item) => (
          <ShoppingListItemCard
            key={item.id}
            canWrite={canWrite}
            item={item}
            currency={currency}
            onToggle={() => handleTogglePurchased(item.id, item.is_purchased)}
            onDelete={() => handleDeleteItem(item.id)}
          />
        ))}
        {purchasedItems.map((item) => (
          <ShoppingListItemCard
            key={item.id}
            canWrite={canWrite}
            item={item}
            currency={currency}
            onToggle={() => handleTogglePurchased(item.id, item.is_purchased)}
            onDelete={() => handleDeleteItem(item.id)}
          />
        ))}

        {list.items?.length === 0 && (
          <div className="col-span-full bg-surface-card rounded-3xl p-12 text-center border border-dashed border-border">
            <ShoppingCart size={48} className="mx-auto mb-4 text-on-muted" />
            <h3 className="text-xl font-semibold text-on mb-2">
              {t("detail.empty")}
            </h3>
            {canWrite && (
              <p className="text-on-secondary mb-8">
                {recipesEnabled
                  ? t("detail.emptySubtitleRecipes", {
                      defaultValue: "Add items manually or from a recipe.",
                    })
                  : t("detail.emptySubtitle", {
                      defaultValue: "Add items manually.",
                    })}
              </p>
            )}
            {canWrite && (
              <Button onClick={() => setShowAddModal(true)} className="gap-2">
                <Plus size={20} />
                {t("detail.addItem")}
              </Button>
            )}
          </div>
        )}
      </div>

      {showAddModal && (
        <TypedSlot
          name="shopping_list_add_item"
          data={{
            listId: id!,
            onClose: () => setShowAddModal(false),
            onSuccess: () => {
              setShowAddModal(false);
              invalidation.shoppingLists(queryClient);
            },
          }}
        />
      )}
      {showRecipesModal && id && (
        <AddFromRecipesModal
          listId={id}
          onClose={() => setShowRecipesModal(false)}
          onSuccess={() => {
            setShowRecipesModal(false);
            invalidation.shoppingLists(queryClient);
          }}
        />
      )}
      <ConfirmDialog {...confirmDialogProps} />
    </div>
  );
}
