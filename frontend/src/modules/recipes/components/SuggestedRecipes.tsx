import { AlertTriangle, Clock, Sparkles } from "lucide-react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/Button";
import { EmptyState } from "@/components/ui/EmptyState";
import LoadingSpinner from "@/components/LoadingSpinner";
import {
  StockCoverage,
  toneForCoverage,
} from "@/modules/shared/components/StockCoverage";
import type { SuggestedRecipe } from "@/modules/recipes/types/mealplans";

interface SuggestedRecipesProps {
  suggestions: SuggestedRecipe[];
  isLoading: boolean;
  onSelect: (recipe: SuggestedRecipe) => void;
  t: (key: string, opts?: Record<string, unknown>) => string;
}

/**
 * The suggestion's ingredient coverage, written as the recipe cards write it.
 *
 * This used to be a percent icon followed by a bare number — "⁒ 100" — with
 * no title and no accessible name, so a screen reader announced "100" and a
 * sighted reader got a 16px glyph beside 12px text. The percentage came from
 * the same count the card shows as a ratio.
 */
export function AvailabilityBadge({
  available,
  total,
}: {
  available: number;
  total: number;
}) {
  const tone = toneForCoverage(available, total);
  const color =
    tone === "ok"
      ? "text-on-success bg-success-50"
      : tone === "partial"
        ? "text-on-warning bg-amber-50"
        : "text-on-danger bg-red-50";
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 text-xs font-medium px-1.5 py-0.5 rounded-full",
        color,
      )}
    >
      <StockCoverage available={available} total={total} tone={tone} />
    </span>
  );
}

function ExpiryBadge({ score, label }: { score: number; label: string }) {
  if (score < 0.4) return null;
  const color =
    score >= 0.8 ? "text-on-danger bg-red-50" : "text-on-warning bg-amber-50";
  return (
    <span
      className={cn(
        "inline-flex items-center gap-0.5 text-xs font-medium px-1.5 py-0.5 rounded-full",
        color,
      )}
    >
      <AlertTriangle size={16} aria-hidden="true" />
      <span className="sr-only">{label}</span>
    </span>
  );
}

export function SuggestedRecipes({
  suggestions,
  isLoading,
  onSelect,
  t,
}: SuggestedRecipesProps) {
  if (isLoading) {
    return <LoadingSpinner />;
  }

  if (suggestions.length === 0) {
    return (
      <EmptyState
        variant="compact"
        icon={Sparkles}
        title={t("recipes:meal_planner.no_suggestions")}
      />
    );
  }

  return (
    <div className="flex flex-col gap-2">
      {suggestions.map((recipe) => (
        <Button
          key={recipe.recipe_id}
          type="button"
          variant="outline"
          size="row"
          onClick={() => onSelect(recipe)}
          className="hover:border-accent hover:bg-accent/5 transition-colors"
        >
          {recipe.image_url ? (
            <img
              src={recipe.image_url}
              alt={recipe.name}
              loading="lazy"
              className="w-12 h-12 rounded object-cover flex-shrink-0"
            />
          ) : (
            <div className="w-12 h-12 rounded bg-surface-inset flex-shrink-0" />
          )}
          <div className="flex-1 min-w-0">
            <p className="text-sm font-medium truncate">{recipe.name}</p>
            <div className="flex items-center gap-2 mt-0.5">
              {recipe.prep_time_minutes && (
                <span className="flex items-center gap-0.5 text-xs text-on-muted">
                  <Clock size={16} />
                  {t("recipes:recipe.prep_time_minutes", {
                    count: recipe.prep_time_minutes,
                  })}
                </span>
              )}
              {recipe.ingredients_total > 0 && (
                <AvailabilityBadge
                  available={recipe.ingredients_available}
                  total={recipe.ingredients_total}
                />
              )}
              {recipe.expiry_urgency_score > 0 && (
                <ExpiryBadge
                  score={recipe.expiry_urgency_score}
                  label={t("recipes:meal_planner.expiry_urgent")}
                />
              )}
            </div>
          </div>
        </Button>
      ))}
    </div>
  );
}
