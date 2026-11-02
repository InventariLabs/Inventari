import {
  Star,
  ChefHat,
  Clock,
  Copy,
  Pencil,
  Trash2,
  CheckCircle2,
  Circle,
} from "lucide-react";
import { memo } from "react";
import { Link } from "react-router-dom";
import { useDraggable } from "@dnd-kit/core";

import { DND_LABEL } from "@/lib/dndA11y";
import { CSS } from "@dnd-kit/utilities";
import type { TFunction } from "i18next";
import { Card } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { cn } from "@/lib/utils";
import {
  StockCoverage,
  toneForCoverage,
} from "@/modules/shared/components/StockCoverage";
import type { RecipeList } from "@/modules/recipes/types/core";

interface RecipeCardProps {
  recipe: RecipeList;
  selectedTags: string[];
  tagColorMap: Map<string, string | null>;
  selectionMode: boolean;
  selected: boolean;
  dragEnabled: boolean;
  /** Whether to offer the actions that change the recipe. */
  canWrite?: boolean;
  onToggleSelect: (id: string) => void;
  onToggleFavorite: (recipe: RecipeList) => void;
  onEdit: (recipe: RecipeList) => void;
  onDelete: (id: string) => void;
  onDuplicate: (recipe: RecipeList) => void;
  onTagClick: (tag: string) => void;
  linkTo: string;
  t: TFunction;
}

export const RecipeCard = memo(function RecipeCard({
  recipe,
  selectedTags,
  tagColorMap,
  selectionMode,
  selected,
  dragEnabled,
  canWrite = true,
  onToggleSelect,
  onToggleFavorite,
  onEdit,
  onDelete,
  onDuplicate,
  onTagClick,
  linkTo,
  t,
}: RecipeCardProps) {
  const { attributes, listeners, setNodeRef, transform, isDragging } =
    useDraggable({
      id: `recipe-card:${recipe.id}`,
      data: { type: "recipe", recipeId: recipe.id, [DND_LABEL]: recipe.name },
      disabled: !dragEnabled,
    });

  const dragStyle = {
    transform: CSS.Translate.toString(transform),
    opacity: isDragging ? 0.4 : 1,
    zIndex: isDragging ? 30 : undefined,
  };

  const coverageTone = toneForCoverage(
    recipe.ingredients_available,
    recipe.ingredients_total,
  );

  return (
    <Card
      data-testid="recipe-card"
      className={cn(
        "relative flex flex-col overflow-hidden p-0 cursor-pointer hover:shadow-md transition group",
        selectionMode && selected && "ring-2 ring-primary-400",
      )}
    >
      {selectionMode && (
        <Button
          type="button"
          variant="ghost"
          size="inline"
          data-testid="recipe-select-btn"
          onClick={(e) => {
            e.stopPropagation();
            onToggleSelect(recipe.id);
          }}
          aria-label={
            selected ? t("recipes:bulk.deselect") : t("recipes:bulk.select")
          }
          className="absolute top-2 left-2 z-10 p-0.5 text-on-muted hover:text-primary-600 hover:bg-transparent"
        >
          {selected ? (
            <CheckCircle2 size={16} className="text-primary-600" />
          ) : (
            <Circle size={16} />
          )}
        </Button>
      )}
      <Link
        to={linkTo}
        ref={setNodeRef}
        style={dragStyle}
        {...(dragEnabled ? { ...attributes, ...listeners } : {})}
        className={cn(
          "flex flex-1 flex-col",
          dragEnabled && "cursor-grab active:cursor-grabbing",
        )}
      >
        {recipe.image_url ? (
          <img
            src={recipe.image_url}
            alt={recipe.name}
            loading="lazy"
            className="w-full aspect-video object-cover"
          />
        ) : (
          <div
            data-testid="recipe-image-placeholder"
            className="w-full h-12 bg-surface-raised/40 border-b border-border flex items-center justify-center text-on-muted"
          >
            <ChefHat size={14} />
          </div>
        )}

        <div className="p-4 flex flex-col gap-2 flex-1">
          <div className="flex items-start justify-between gap-2">
            <h3 className="font-semibold text-on text-sm leading-snug line-clamp-2 flex-1">
              {recipe.name}
            </h3>
            <div className="flex items-center gap-1 shrink-0">
              {canWrite && (
                <Button
                  onClick={(e) => {
                    e.stopPropagation();
                    onToggleFavorite(recipe);
                  }}
                  variant="ghost"
                  size="iconSm"
                  aria-label={t("common:a11y.favorite")}
                  className="text-on-muted hover:text-amber-500 min-h-11 min-w-11 md:min-h-0 md:min-w-0"
                >
                  {recipe.is_favorite ? (
                    <Star size={16} className="text-amber-500 fill-amber-500" />
                  ) : (
                    <Star size={16} className="text-on-muted" />
                  )}
                </Button>
              )}
              {/* A reader cannot set it — the endpoint asks for
                  `recipes:write` — but "this one is a favourite" is worth
                  knowing, so the mark stays and only the control goes. */}
              {!canWrite && recipe.is_favorite && (
                <Star
                  size={16}
                  className="text-amber-500 fill-amber-500"
                  aria-label={t("common:a11y.favorite")}
                />
              )}
            </div>
          </div>

          {recipe.description && (
            <p className="text-xs text-on-secondary line-clamp-2">
              {recipe.description}
            </p>
          )}

          <div className="flex flex-wrap items-center gap-1.5 mt-auto pt-2">
            <span className="text-xs text-on-secondary flex items-center gap-1">
              <ChefHat size={11} />
              {t("recipes:card.servings", { count: recipe.servings })}
            </span>
            {recipe.prep_time_minutes && (
              <span className="text-xs text-on-secondary flex items-center gap-1">
                <Clock size={11} />
                {t("recipes:recipe.prep_time", {
                  minutes: recipe.prep_time_minutes,
                })}
              </span>
            )}
            {/* One badge for both tabs. The "I can cook" tab used to render
                the same fraction as a percentage, which is the ratio rounded:
                80% of five ingredients cannot be read back as "4 of 5", and
                the one that is missing is the point. */}
            {recipe.ingredients_total > 0 && (
              <Badge
                variant={
                  coverageTone === "ok"
                    ? "success"
                    : coverageTone === "partial"
                      ? "warning"
                      : "danger"
                }
                className="gap-1"
              >
                <StockCoverage
                  available={recipe.ingredients_available}
                  total={recipe.ingredients_total}
                  incomparable={recipe.ingredients_incomparable}
                  tone={coverageTone}
                />
              </Badge>
            )}
            {recipe.tags?.slice(0, 2).map((tag) => {
              const color = tagColorMap.get(tag);
              const isTagSelected = selectedTags.includes(tag);
              return (
                <Button
                  key={tag}
                  type="button"
                  variant="outline"
                  size="contentSm"
                  aria-pressed={isTagSelected}
                  className={cn(
                    "gap-1 rounded-full text-xs font-medium px-2.5 py-1",
                    isTagSelected
                      ? "bg-primary-50 border-primary-500 text-on"
                      : "bg-surface-raised border-border text-on-secondary hover:border-primary-200 hover:text-on",
                  )}
                  onClick={(e) => {
                    e.stopPropagation();
                    onTagClick(tag);
                  }}
                >
                  {color && (
                    <span
                      className="w-2.5 h-2.5 rounded-full shrink-0"
                      style={{ backgroundColor: color }}
                    />
                  )}
                  {tag}
                </Button>
              );
            })}
          </div>
        </div>
      </Link>

      {canWrite && (
        <div className="flex justify-end gap-1 px-4 pb-3 transition-opacity md:opacity-0 md:group-hover:opacity-100 md:group-focus-within:opacity-100">
          <Button
            onClick={() => onEdit(recipe)}
            variant="outline"
            size="iconSm"
            aria-label={t("common:a11y.edit")}
            className="shadow-sm hover:text-primary-600 hover:border-primary-300 hover:bg-transparent min-h-11 min-w-11 md:min-h-0 md:min-w-0"
          >
            <Pencil size={16} />
          </Button>
          <Button
            data-testid="recipe-duplicate-btn"
            onClick={() => onDuplicate(recipe)}
            variant="outline"
            size="iconSm"
            aria-label={t("recipes:actions.duplicate")}
            className="shadow-sm hover:text-primary-600 hover:border-primary-300 hover:bg-transparent min-h-11 min-w-11 md:min-h-0 md:min-w-0"
          >
            <Copy size={16} />
          </Button>
          <Button
            data-testid="recipe-delete-btn"
            onClick={() => onDelete(recipe.id)}
            variant="ghostDanger"
            size="iconSm"
            aria-label={t("common:a11y.delete")}
            className="shadow-sm min-h-11 min-w-11 md:min-h-0 md:min-w-0"
          >
            <Trash2 size={16} />
          </Button>
        </div>
      )}
    </Card>
  );
});
