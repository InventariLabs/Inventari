import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate, useParams } from "react-router-dom";
import { BookOpen, FlaskConical, Star, Trash2, Wallet } from "lucide-react";
import { toast } from "sonner";
import { extractApiError, isNotFoundError } from "@/lib/errors";
import { useModulePageHeader } from "@/hooks/useModulePageHeader";
import { useCanManage } from "@/hooks/useCanWrite";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { QueryError } from "@/components/ui/QueryResult";
import { RecordNotFound } from "@/components/ui/RecordNotFound";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/Tabs";
import {
  useDeleteMakerRecipe,
  useMakerRecipe,
  useUpdateMakerRecipe,
} from "@/modules/maker/hooks/useRecipes";
import { AvailabilityBadge } from "@/modules/maker/components/AvailabilityBadge";
import { CompositionTab } from "@/modules/maker/pages/tabs/CompositionTab";
import { CostResultTab } from "@/modules/maker/pages/tabs/CostResultTab";
import { HistoryTab } from "@/modules/maker/pages/tabs/HistoryTab";
import { formatDate } from "@/utils/helpers";
import { formatQuantityLocalized } from "@/lib/i18nHelpers";

type TabKey = "composition" | "cost" | "history";

export default function RecipeDetailPage() {
  const { recipeId } = useParams<{ recipeId: string }>();
  const { t } = useTranslation("maker");
  const navigate = useNavigate();
  const { setHeader } = useModulePageHeader();
  // A formula decides what production takes from stock, so writing it —
  // including deleting it — belongs to maker:manage, not to the floor.
  const canManage = useCanManage("maker");
  const [activeTab, setActiveTab] = useState<TabKey>("composition");
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);

  const { data: recipe, isLoading, error, refetch } = useMakerRecipe(recipeId);

  // Deleting a formula lived on the removed /maker/bom screen, where it
  // deleted "the recipe of this product" — meaningless once a product can
  // have several. Here it deletes the one on screen.
  const deleteRecipe = useDeleteMakerRecipe();
  // The first formula of a product is born default and stays that way until
  // someone names another one — the flip lives on the update path, under the
  // same lock that creation takes, so the demotion and the election are one
  // transaction. This is the door to it; `mutate` is referentially stable
  // (mutationFactory), which is what lets it sit in this effect.
  const { mutate: setDefaultMutate } = useUpdateMakerRecipe();

  useEffect(() => {
    if (!recipe) return;
    setHeader({
      title: recipe.name,
      subtitle: recipe.output_template_name ?? undefined,
      backTo: "/maker",
      actions: canManage ? (
        <>
          {!recipe.is_default && (
            <Button
              variant="outline"
              leftIcon={<Star size={16} />}
              // Naming this formula the default demotes the previous one —
              // the backend does both under one lock. The toast says the
              // choice landed, because the badge is the only visible
              // consequence.
              onClick={() =>
                setDefaultMutate(
                  { recipeId: recipe.id, data: { is_default: true } },
                  {
                    onSuccess: () =>
                      toast.success(t("detail.setDefaultSuccess")),
                    onError: (err) => {
                      toast.error(
                        extractApiError(err, t("detail.setDefaultFailed")),
                      );
                    },
                  },
                )
              }
              data-testid="maker-recipe-set-default"
            >
              {t("detail.setAsDefault")}
            </Button>
          )}
          {/* A safe action and a destructive one share this row: the divider
              keeps them apart, and the delete's own variant carries the
              warning at rest — a touch screen has no hover (UI_GUIDELINES
              §2.13a). */}
          {recipe.is_default ? null : (
            <span aria-hidden className="w-px h-5 shrink-0 bg-border mx-1" />
          )}
          <Button
            variant="ghostDanger"
            leftIcon={<Trash2 size={16} />}
            onClick={() => setShowDeleteConfirm(true)}
            data-testid="maker-recipe-delete"
          >
            {t("detail.deleteRecipe")}
          </Button>
        </>
      ) : undefined,
    });
  }, [recipe, setHeader, t, canManage, setDefaultMutate]);

  function handleDelete() {
    if (!recipe) return;
    deleteRecipe.mutate(recipe.id, {
      onSuccess: () => {
        toast.success(t("detail.recipeDeleted"));
        navigate("/maker");
      },
      onError: (err) => {
        toast.error(extractApiError(err, t("detail.recipeDeleteFailed")));
      },
    });
  }

  if (isLoading) {
    return (
      <div className="text-center py-12 text-on-muted">
        {t("bomDetail.loading")}
      </div>
    );
  }

  // A recipe that was deleted is not a failed request: one of the two is worth
  // asking about again, and the other never will be.
  if (error && !isNotFoundError(error)) {
    return <QueryError onRetry={() => void refetch()} />;
  }

  if (!recipe) {
    return (
      <RecordNotFound
        title={t("bomDetail.notFound")}
        backTo="/maker"
        backLabel={t("bomDetail.back")}
      />
    );
  }

  return (
    <div className="space-y-4 animate-in fade-in slide-in-from-bottom-4 duration-500">
      {/* MakerRecipe summary */}
      <Card className="p-4 flex flex-col sm:flex-row sm:items-center gap-3">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <h2 className="text-lg font-semibold text-on">{recipe.name}</h2>
            {recipe.is_default && (
              <span className="text-[10px] font-medium uppercase text-accent bg-accent/10 px-2 py-0.5 rounded-full">
                {t("catalog.default")}
              </span>
            )}
          </div>
          <p className="text-sm text-on-muted mt-0.5">
            {t("composition.batchYield", {
              qty: formatQuantityLocalized(
                t,
                recipe.batch_yield_qty,
                recipe.batch_yield_uom_symbol,
              ),
            })}
          </p>
          <AvailabilityBadge recipeId={recipe.id} className="mt-1" />
          {recipe.source_recipe_id && (
            <p className="text-xs text-on-muted mt-1 flex items-center gap-1">
              <BookOpen size={12} />
              {t("detail.sourceRecipe", {
                date: formatDate(recipe.source_snapshot_at),
              })}
            </p>
          )}
        </div>
      </Card>

      <Tabs
        defaultValue="composition"
        value={activeTab}
        onValueChange={(v) => setActiveTab(v as TabKey)}
      >
        <TabsList className="w-full sm:w-auto">
          <TabsTrigger value="composition" icon={<FlaskConical size={16} />}>
            {t("detail.tabs.composition")}
          </TabsTrigger>
          <TabsTrigger value="cost" icon={<Wallet size={16} />}>
            {t("detail.tabs.cost")}
          </TabsTrigger>
          <TabsTrigger value="history" icon={<BookOpen size={16} />}>
            {t("detail.tabs.history")}
          </TabsTrigger>
        </TabsList>

        <TabsContent value="composition">
          <CompositionTab recipe={recipe} />
        </TabsContent>
        <TabsContent value="cost">
          <CostResultTab recipe={recipe} />
        </TabsContent>
        <TabsContent value="history">
          <HistoryTab recipe={recipe} />
        </TabsContent>
      </Tabs>

      <ConfirmDialog
        open={showDeleteConfirm}
        title={t("detail.deleteConfirm.title")}
        message={t("detail.deleteConfirm.description")}
        confirmLabel={t("detail.deleteRecipe")}
        variant="danger"
        onConfirm={() => {
          setShowDeleteConfirm(false);
          handleDelete();
        }}
        onCancel={() => setShowDeleteConfirm(false)}
      />
    </div>
  );
}
