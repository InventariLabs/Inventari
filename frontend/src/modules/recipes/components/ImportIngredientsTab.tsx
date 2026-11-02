import { useState } from "react";
import { useTranslation } from "react-i18next";
import { ListPlus, Plus } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { EmptyState } from "@/components/ui/EmptyState";
import { InlineQueryError } from "@/components/ui/QueryResult";
import { useFlatUoms } from "@/modules/shared/hooks/useUoms";
import ImportIngredientRow from "./ImportIngredientRow";
import type { DraftValue, IngredientDraft } from "./importReviewUtils";

interface ImportIngredientsTabProps {
  ingredients: IngredientDraft[];
  /** Whether any line still has the text it was parsed from to switch to. */
  hasOriginalText: boolean;
  onUpdate: (
    key: number,
    field: keyof IngredientDraft,
    value: DraftValue,
  ) => void;
  onRemove: (key: number) => void;
  onAdd: () => void;
}

/**
 * The review sheet's ingredient list. It reads the unit catalogue itself: the
 * rows judge an imported unit against it, so a failed read has to be said
 * here, once, instead of every row quietly calling its unit unrecognised.
 */
export default function ImportIngredientsTab({
  ingredients,
  hasOriginalText,
  onUpdate,
  onRemove,
  onAdd,
}: ImportIngredientsTabProps) {
  const { t } = useTranslation("recipes");
  const {
    data: flatUoms = [],
    isError: unitsFailed,
    error: unitsLoadError,
    refetch: refetchUnits,
  } = useFlatUoms();
  const [showOriginal, setShowOriginal] = useState(true);

  return (
    <>
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-on">
          {t("recipe.ingredients")} ({ingredients.length})
        </h3>
        {hasOriginalText && (
          <Button
            type="button"
            variant="ghost"
            size="contentSm"
            onClick={() => setShowOriginal((v) => !v)}
            className="min-h-11 md:min-h-0 min-w-11 md:min-w-0 px-0 text-xs text-primary-600 hover:text-primary-700 hover:bg-transparent"
          >
            {showOriginal
              ? t("import_export.review_parsed")
              : t("import_export.review_original")}
          </Button>
        )}
      </div>

      {unitsFailed && (
        <InlineQueryError
          error={unitsLoadError}
          onRetry={() => void refetchUnits()}
        />
      )}

      {ingredients.length === 0 ? (
        <EmptyState
          variant="compact"
          icon={ListPlus}
          title={t("import_export.review_no_ingredients")}
        />
      ) : (
        <div className="space-y-2">
          {ingredients.map((ing, idx) => (
            <ImportIngredientRow
              key={ing._key}
              ing={ing}
              idx={idx}
              showOriginal={showOriginal}
              flatUoms={flatUoms}
              onUpdate={onUpdate}
              onRemove={onRemove}
              t={t}
            />
          ))}
        </div>
      )}

      <Button
        type="button"
        variant="outline"
        size="sm"
        onClick={onAdd}
        className="mt-2 gap-1"
      >
        <Plus size={16} />
        {t("import_export.review_add_ingredient")}
      </Button>
    </>
  );
}
