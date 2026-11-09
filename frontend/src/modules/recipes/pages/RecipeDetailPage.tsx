import { useState, useEffect, useCallback, useRef } from "react";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { useParams, useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { ChefHat, ExternalLink } from "lucide-react";
import { toast } from "sonner";

import { extractApiError } from "@/lib/errors";
import {
  useRecipe,
  useUpdateRecipe,
  useDeleteRecipe,
  useDuplicateRecipe,
  useUploadRecipeImage,
  useDeleteRecipeImage,
  useRecipeNutrition,
  useRecipeCost,
} from "../hooks/useRecipes";
import RecipeForm from "../components/RecipeForm";
import { RecipeDetailActions } from "../components/RecipeDetailActions";
import { NUTRITION_COMPLETE_COVERAGE } from "../components/NutritionCard";
import RecipeNutritionSection from "../components/RecipeNutritionSection";
import RecipeCookingHistory from "../components/RecipeCookingHistory";
import RecipeAvailabilityChecker from "../components/RecipeAvailabilityChecker";
import RecipeCostSection from "../components/RecipeCostSection";
import { InstructionsView } from "../components/InstructionsView";
import { RecipeCookingFlow } from "../components/RecipeCookingFlow";
import { RecipePrintView } from "../components/RecipePrintView";
import { Card } from "@/components/ui/Card";
import { isNotFoundError } from "@/lib/errors";
import { QueryError } from "@/components/ui/QueryResult";
import { RecordNotFound } from "@/components/ui/RecordNotFound";
import { webLinkOrNull } from "@/lib/utils";
import { useModulePageHeader } from "@/hooks/useModulePageHeader";
import { useCanWrite } from "@/hooks/useCanWrite";
import { useHasPermission } from "@/hooks/useHasPermission";
import { ReadOnlyNotice } from "@/components/ui/ReadOnlyNotice";
import { useOrganizationCurrency } from "@/hooks/useOrganizationCurrency";
import { useRecordVisit } from "@/module-sdk";
import { RecipeHeroCard } from "./RecipeHeroCard";
import type { RecipeUpdate } from "@/modules/recipes/types/core";
import LoadingSpinner from "@/components/LoadingSpinner";

const UUID_RE =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export default function RecipeDetailPage() {
  const { id } = useParams<{ id: string }>();
  const { t } = useTranslation(["recipes", "common"]);
  const navigate = useNavigate();

  // Guard against non-UUID ids (e.g. /recipes/meal-plans): they collide with
  // collection API routes and would render garbage instead of "not found".
  const recipeId = id && UUID_RE.test(id) ? id : undefined;

  const [servings, setServings] = useState<number | null>(null);
  const [showEdit, setShowEdit] = useState(false);
  const [showPicking, setShowPicking] = useState(false);
  const [showCooking, setShowCooking] = useState(false);
  const [justCompleted, setJustCompleted] = useState(false);
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);
  const [tagInput, setTagInput] = useState("");

  const recipeQuery = useRecipe(recipeId);
  const recipe = recipeQuery.data;
  useRecordVisit("recipes", recipe);

  const activeServings = servings ?? recipe?.servings ?? 1;

  // do not fire nutrition/cost with a guessed "servings=1" before the
  // recipe loads — gate both queries on the recipe being present.
  const nutritionQuery = useRecipeNutrition(
    recipe ? recipeId : undefined,
    activeServings,
  );
  const costQuery = useRecipeCost(
    recipe ? recipeId : undefined,
    activeServings,
  );
  // The cost payload names its own currency; when it does not, the org's is
  // the only honest answer. Both surfaces used to print a hardcoded "PLN".
  const orgCurrency = useOrganizationCurrency();

  const updateMutation = useUpdateRecipe();
  const deleteMutation = useDeleteRecipe();
  const duplicateMutation = useDuplicateRecipe();
  const uploadImageMutation = useUploadRecipeImage();
  const deleteImageMutation = useDeleteRecipeImage();

  const { setHeader } = useModulePageHeader();
  const canWrite = useCanWrite("recipes");
  // Finishing a picking or cooking session takes stock off the shelf, and
  // that endpoint asks for its own key rather than the module's write.
  const canConsume = useHasPermission("recipes:consume");

  const recipeRef = useRef(recipe);
  recipeRef.current = recipe;
  const updateMutationRef = useRef(updateMutation);
  updateMutationRef.current = updateMutation;
  const duplicateMutationRef = useRef(duplicateMutation);
  duplicateMutationRef.current = duplicateMutation;

  // `mutate` here and in `addTag`: their buttons await nothing, so the
  // factory's toast is where a refusal is read.
  const toggleFavorite = useCallback(() => {
    const current = recipeRef.current;
    if (!current || !id) return;
    updateMutationRef.current.mutate({
      id,
      data: { is_favorite: !current.is_favorite },
    });
  }, [id]);

  const handleDuplicate = useCallback(async () => {
    if (!id) return;
    try {
      const copy = await duplicateMutationRef.current.mutateAsync(id);
      toast.success(t("toasts.duplicated"));
      navigate(`/recipes/${copy.id}`);
    } catch (error) {
      toast.error(extractApiError(error, t("errors.save_failed")));
    }
  }, [id, navigate, t]);

  useEffect(() => {
    if (!recipe) return;
    setHeader({
      title: recipe.name,
      subtitle: recipe.description || undefined,
      backTo: "/recipes",
      statusBadge: (
        <span className="flex items-center gap-2">
          {/* No favourite star here: the header action bar renders one a few
              pixels away, filled when the recipe is a favourite. Two stars
              side by side read as two different states rather than one
              indicator plus its toggle. */}
          {/* source attribution belongs to the header, not to a
              loose link floating below the last card. Rows written before
              source_url was validated may hold anything, so a non-web value
              renders as text instead of a link. */}
          {recipe.source_url &&
            (webLinkOrNull(recipe.source_url) ? (
              <a
                href={webLinkOrNull(recipe.source_url)!}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1 text-xs font-medium text-on-primary hover:underline"
              >
                {t("recipe.source_url")}
                <ExternalLink size={11} />
              </a>
            ) : (
              <span className="text-xs text-on-muted">
                {t("recipe.source_url")}
              </span>
            ))}
        </span>
      ),
      actions: (
        <RecipeDetailActions
          recipe={recipe}
          justCompleted={justCompleted}
          hasInstructions={Boolean(recipe.instructions)}
          onToggleFavorite={toggleFavorite}
          onDuplicate={handleDuplicate}
          onEdit={() => setShowEdit(true)}
          onDelete={() => setShowDeleteConfirm(true)}
          onStartPicking={() => setShowPicking(true)}
          onStartCooking={() => setShowCooking(true)}
          canWrite={canWrite}
          canConsume={canConsume}
        />
      ),
    });
  }, [
    recipe,
    setHeader,
    toggleFavorite,
    t,
    justCompleted,
    handleDuplicate,
    canWrite,
    canConsume,
  ]);

  const handleUpdate = async (data: RecipeUpdate) => {
    if (!id) return;
    try {
      await updateMutation.mutateAsync({ id, data });
      toast.success(t("toasts.saved"));
      setShowEdit(false);
    } catch (error) {
      toast.error(extractApiError(error, t("errors.save_failed")));
    }
  };

  const handleDelete = async () => {
    if (!id) return;
    try {
      await deleteMutation.mutateAsync(id);
      navigate("/recipes");
    } catch (error) {
      toast.error(extractApiError(error, t("errors.delete_failed")));
    }
  };

  const addTag = (tag: string) => {
    const trimmed = tag.trim().toLowerCase();
    if (!trimmed || !recipe || !id) return;
    if (recipe.tags?.includes(trimmed)) return;
    updateMutation.mutate(
      { id, data: { tags: [...(recipe.tags ?? []), trimmed] } },
      { onSuccess: () => setTagInput("") },
    );
  };

  const handleImageUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file || !id) return;
    try {
      await uploadImageMutation.mutateAsync({ id, file });
      toast.success(t("image.upload_success"));
    } catch (error) {
      // "File too large" names the fix; the generic sentence did not.
      toast.error(extractApiError(error, t("errors.image_failed")));
    }
    e.target.value = "";
  };

  const handleDeleteImage = async () => {
    if (!id) return;
    try {
      await deleteImageMutation.mutateAsync(id);
    } catch (error) {
      toast.error(extractApiError(error, t("errors.image_failed")));
    }
  };

  if (recipeQuery.isLoading) {
    return <LoadingSpinner />;
  }

  // A failed request and a recipe that does not exist are two different
  // answers: the first one is worth retrying, the second one never is — which
  // the branch below used to say and the one above used to undo, because it
  // caught the 404 first and offered "try again" for a recipe that was gone.
  if (recipeQuery.isError && !isNotFoundError(recipeQuery.error)) {
    return <QueryError onRetry={() => recipeQuery.refetch()} />;
  }

  if (!recipe) {
    return (
      <RecordNotFound
        icon={ChefHat}
        title={t("notFound")}
        backTo="/recipes"
        backLabel={t("backToList")}
      />
    );
  }

  return (
    <>
      {/* Screen content — hidden when printing */}
      {/* Sections space themselves — the cards used to carry `mb-4` each, so a
          card that was conditionally hidden took its spacing with it. */}
      <div className="flex flex-col gap-6 pb-28 print:hidden animate-in fade-in duration-300 motion-reduce:animate-none">
        <ReadOnlyNotice module="recipes" />
        {/* Hero image card */}
        <RecipeHeroCard
          canWrite={canWrite}
          recipe={recipe}
          nutritionCalories={
            nutritionQuery.data &&
            nutritionQuery.data.coverage >= NUTRITION_COMPLETE_COVERAGE
              ? (nutritionQuery.data.per_serving.calories_kcal ?? undefined)
              : undefined
          }
          estimatedCost={costQuery.data?.estimated_cost ?? undefined}
          currency={costQuery.data?.currency ?? orgCurrency}
          uploadImageMutation={uploadImageMutation}
          deleteImageMutation={deleteImageMutation}
          onImageUpload={handleImageUpload}
          onDeleteImage={handleDeleteImage}
          onEditRequest={() => setShowEdit(true)}
          tagInput={tagInput}
          onTagInputChange={setTagInput}
          onAddTag={addTag}
          t={t}
        />

        {/* two columns — ingredients sticky on the left, instructions
            with nutrition and cost on the right. The split starts at xl, not
            lg: at 1024px the left column is only ~400px wide and the
            ingredient rows have to clip their names to fit. The 32rem floor
            keeps the ingredient name readable next to its quantity, unit and
            "link to product" action at the narrow end of the split. Below xl
            the stack order stays unchanged. */}
        <div className="xl:grid xl:grid-cols-[minmax(32rem,2fr)_minmax(0,3fr)] xl:gap-5 xl:items-start">
          <div className="xl:sticky xl:top-4">
            <RecipeAvailabilityChecker
              recipeId={id!}
              activeServings={activeServings}
              onServingsChange={setServings}
            />
          </div>

          <div className="min-w-0">
            {/* Instructions */}
            {recipe.instructions && (
              <Card className="p-0 shadow-sm">
                <div className="px-5 py-3 border-b border-border">
                  <h2 className="text-sm font-semibold text-on-secondary">
                    {t("recipe.instructions")}
                  </h2>
                </div>
                <div className="px-5 py-4">
                  <InstructionsView text={recipe.instructions} />
                </div>
              </Card>
            )}

            <RecipeNutritionSection
              recipeId={id!}
              activeServings={activeServings}
              onEditRecipe={canWrite ? () => setShowEdit(true) : undefined}
            />

            <RecipeCostSection
              recipeId={id!}
              activeServings={activeServings}
              onEditRecipe={canWrite ? () => setShowEdit(true) : undefined}
            />
          </div>
        </div>

        <RecipeCookingHistory recipeId={id!} />

        {/* Modals */}
        {showEdit && recipe && (
          <RecipeForm
            initial={recipe}
            onSubmit={handleUpdate}
            onCancel={() => setShowEdit(false)}
            isLoading={updateMutation.isPending}
          />
        )}

        <RecipeCookingFlow
          recipeId={recipe.id}
          recipeName={recipe.name}
          instructions={recipe.instructions}
          ingredients={recipe.ingredients}
          activeServings={activeServings}
          baseServings={recipe.servings}
          picking={showPicking}
          cooking={showCooking}
          onPickingClose={(completed) => {
            setShowPicking(false);
            if (completed) {
              setJustCompleted(true);
              recipeQuery.refetch();
            }
          }}
          onCookingClose={() => setShowCooking(false)}
        />

        <ConfirmDialog
          open={showDeleteConfirm}
          variant="danger"
          title={t("actions.delete")}
          message={t("actions.delete_confirm", { name: recipe.name })}
          confirmLabel={t("actions.delete")}
          cancelLabel={t("common:form.cancel")}
          onCancel={() => setShowDeleteConfirm(false)}
          onConfirm={handleDelete}
        />
      </div>

      {/* Print-only recipe card — must be a sibling of the print:hidden container, not a child */}
      <RecipePrintView
        recipe={recipe}
        servings={activeServings}
        nutrition={nutritionQuery.data}
        cost={costQuery.data}
        currency={orgCurrency}
      />
    </>
  );
}
