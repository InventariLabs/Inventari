import { useTranslation } from "react-i18next";
import { HelpCircle } from "lucide-react";
import { cn } from "@/lib/utils";
import { useMakerRecipeAvailability } from "@/modules/maker/hooks/useRecipes";
import { formatQuantityLocalized } from "@/lib/i18nHelpers";
import {
  StockCoverage,
  toneForCoverage,
} from "@/modules/shared/components/StockCoverage";

interface AvailabilityBadgeProps {
  recipeId: string;
  /** Batch count to check; defaults to 1 ("can I make one batch?"). */
  batches?: string;
  className?: string;
}

export function AvailabilityBadge({
  recipeId,
  batches = "1",
  className,
}: AvailabilityBadgeProps) {
  const { t } = useTranslation("maker");
  const { data, isLoading } = useMakerRecipeAvailability(recipeId, batches);

  if (isLoading || !data) {
    return null;
  }

  // Recipes without ingredients have no availability to report.
  if (data.ingredients.length === 0) {
    return null;
  }

  const shortCount = data.ingredients.filter(
    (i) => i.shortage !== null && Number(i.shortage) > 0,
  ).length;
  const unknownCount = data.ingredients.filter(
    (i) => i.convertible === false,
  ).length;

  // The batch count only exists when every ingredient could be measured
  // against the requirement; otherwise there is no bottleneck to report.
  const maxBatches =
    data.max_batches === null
      ? null
      : formatQuantityLocalized(t, data.max_batches, null);
  const trailer = maxBatches !== null && (
    <span className="text-on-muted font-normal">
      · {t("availability.maxBatches")}: {maxBatches}
    </span>
  );

  // An ingredient whose measure has no bridge to the shelf's is not an
  // ingredient known to be missing, so this branch writes no ratio: "0/1 in
  // stock" would be a count of what nobody counted. Everywhere the numbers
  // are real, the badge writes them the way the recipe cards do.
  if (unknownCount > 0) {
    return (
      <span
        className={cn(
          "inline-flex flex-wrap items-center gap-x-1.5 text-xs font-medium text-amber-600 dark:text-amber-400",
          className,
        )}
        data-testid="availability-badge-unknown"
      >
        <HelpCircle size={14} className="shrink-0" />
        {t("availability.unknown", { count: unknownCount })}
        {trailer}
      </span>
    );
  }

  const inStock = data.ingredients.length - shortCount;
  const tone = toneForCoverage(inStock, data.ingredients.length);

  return (
    <span
      className={cn(
        "inline-flex flex-wrap items-center gap-x-1.5 text-xs font-medium",
        tone === "ok"
          ? "text-accent-700 dark:text-accent-400"
          : tone === "none"
            ? "text-red-600 dark:text-red-400"
            : "text-amber-600 dark:text-amber-400",
        className,
      )}
      data-testid={
        shortCount === 0 ? "availability-badge-ok" : "availability-badge-short"
      }
    >
      <StockCoverage
        available={inStock}
        total={data.ingredients.length}
        tone={tone}
        iconSize={14}
      />
      {trailer}
    </span>
  );
}
