import { format, parseISO } from "date-fns";
import {
  ShoppingCart,
  ExternalLink,
  Clock,
  Package,
  RefreshCw,
} from "lucide-react";
import { Link } from "react-router-dom";
import { Button, buttonVariants } from "@/components/ui/Button";
import { useModules } from "@/contexts/ModulesContext";
import type {
  GeneratedItem,
  ShoppingListGenerationResult,
} from "@/modules/recipes/types/mealplans";
import { dateFnsLocale } from "@/utils/formatters";
import { formatQuantityValue } from "@/utils/formatters";
import { unitLabel } from "@/lib/i18nHelpers";

interface ShoppingListPreviewProps {
  planId: string;
  hasMeals: boolean;
  existingListId?: string | null;
  /** A meal was planned after the list was made, so the list lacks it. */
  mealsAddedSinceList?: boolean;
  generationResult?: ShoppingListGenerationResult;
  isGenerating: boolean;
  onGenerate: () => void;
  /** Whether to offer generating one. The links to an existing list are reads. */
  canWrite?: boolean;
  t: (key: string, opts?: Record<string, unknown>) => string;
}

function groupByBuyTiming(items: GeneratedItem[]) {
  const planStart = items.reduce<string | null>((earliest, item) => {
    if (!item.needed_by) return earliest;
    if (!earliest || item.needed_by < earliest) return item.needed_by;
    return earliest;
  }, null);

  if (!planStart) return { buyNow: items, buyLater: [] };

  const startDay = parseISO(planStart);
  const buyNow: GeneratedItem[] = [];
  const buyLater: GeneratedItem[] = [];

  for (const item of items) {
    if (!item.needed_by) {
      buyNow.push(item);
      continue;
    }
    const diff = parseISO(item.needed_by).getTime() - startDay.getTime();
    const daysDiff = Math.round(diff / 86400000);
    if (daysDiff <= 2) {
      buyNow.push(item);
    } else {
      buyLater.push(item);
    }
  }

  return { buyNow, buyLater };
}

export function ShoppingListPreview({
  hasMeals,
  existingListId,
  mealsAddedSinceList = false,
  generationResult,
  isGenerating,
  onGenerate,
  canWrite = true,
  t,
}: ShoppingListPreviewProps) {
  // writing to a disabled shopping_lists module "succeeded" into an
  // unreachable list — hide the whole section when the module is off.
  const { isModuleEnabled } = useModules();
  if (!isModuleEnabled("shopping_lists")) return null;

  // Generating a list also stamps `shopping_list_id` on the plan, so a
  // link-first order made the summary the backend had just computed
  // unreachable — the freshly generated result is what this run is about.
  // Until a meal is planned after it: the summary then describes a list
  // that lacks that meal, so the list's own row below says so and offers
  // the update.
  if (generationResult && !mealsAddedSinceList) {
    const { buyNow, buyLater } = groupByBuyTiming(generationResult.items || []);

    return (
      <div className="flex flex-col gap-2 p-3 rounded-lg bg-surface-inset/50 text-sm">
        <p className="font-medium">
          {t("recipes:meal_planner.list_generated")}
        </p>
        <p className="text-on-secondary">
          {t("recipes:meal_planner.ingredients_summary", {
            total: generationResult.total_ingredients,
            available: generationResult.available_count,
            to_buy: generationResult.to_buy_count,
          })}
        </p>

        {(buyNow.length > 0 || buyLater.length > 0) && (
          <div className="mt-1 flex flex-col gap-2">
            {buyNow.length > 0 && (
              <div>
                <p className="text-xs font-medium flex items-center gap-1 mb-1">
                  <Package size={12} />
                  {t("recipes:meal_planner.buy_now")}
                </p>
                <div className="flex flex-wrap gap-1">
                  {/* Keyed by position, not by name: since grams stopped
                      being added to pieces one product leaves two lines,
                      and two chips named "Flour" shared a key. The list is
                      rebuilt whole from each generation result, so its
                      position is the one thing that stays true. */}
                  {buyNow.map((item, index) => (
                    <span
                      key={index}
                      className="inline-flex items-center gap-1 text-xs bg-surface px-2 py-0.5 rounded border"
                    >
                      {item.name} ({formatQuantityValue(item.quantity)}
                      {item.uom_symbol
                        ? ` ${unitLabel(t, item.uom_symbol)}`
                        : ""}
                      )
                    </span>
                  ))}
                </div>
              </div>
            )}
            {buyLater.length > 0 && (
              <div>
                <p className="text-xs font-medium flex items-center gap-1 mb-1 text-on-muted">
                  <Clock size={12} />
                  {t("recipes:meal_planner.buy_later")}
                </p>
                <div className="flex flex-wrap gap-1">
                  {buyLater.map((item, index) => (
                    <span
                      key={index}
                      className="inline-flex items-center gap-1 text-xs bg-surface px-2 py-0.5 rounded border border-dashed"
                    >
                      {item.name} ({formatQuantityValue(item.quantity)}
                      {item.uom_symbol
                        ? ` ${unitLabel(t, item.uom_symbol)}`
                        : ""}
                      )
                      {item.needed_by && (
                        <span className="text-on-muted">
                          {format(parseISO(item.needed_by), "EEE d", {
                            locale: dateFnsLocale(),
                          })}
                        </span>
                      )}
                    </span>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}

        <Link
          to={`/shopping-lists/${generationResult.shopping_list_id}`}
          className={buttonVariants({ variant: "secondary", size: "sm" })}
        >
          <ExternalLink size={14} />
          {t("recipes:meal_planner.view_shopping_list")}
        </Link>
      </div>
    );
  }

  if (existingListId) {
    return (
      <div className="flex flex-col gap-2">
        <div className="flex flex-wrap items-center gap-2">
          <Link
            to={`/shopping-lists/${existingListId}`}
            className={buttonVariants({ variant: "secondary", size: "sm" })}
          >
            <ExternalLink size={14} />
            {t("recipes:meal_planner.view_shopping_list")}
          </Link>
          {canWrite && (
            <Button
              variant="outline"
              size="sm"
              onClick={onGenerate}
              disabled={!hasMeals || isGenerating}
              title={
                !hasMeals
                  ? t("recipes:meal_planner.generate_list_disabled_tooltip")
                  : undefined
              }
            >
              {isGenerating ? (
                <RefreshCw size={16} className="mr-1.5 animate-spin" />
              ) : (
                <RefreshCw size={16} className="mr-1.5" />
              )}
              {t("recipes:meal_planner.refresh_shopping_list")}
            </Button>
          )}
        </div>
        {/* The list was made at a moment; meals planned after it are not on
            it until this run. Said only when such a meal exists — a line
            standing under every list stopped being read. */}
        {mealsAddedSinceList && (
          <p className="text-xs text-on-muted">
            {t("recipes:meal_planner.refresh_shopping_list_hint")}
          </p>
        )}
      </div>
    );
  }

  if (!canWrite) return null;

  return (
    <Button
      variant="outline"
      size="sm"
      onClick={onGenerate}
      disabled={!hasMeals || isGenerating}
      title={
        !hasMeals
          ? t("recipes:meal_planner.generate_list_disabled_tooltip")
          : undefined
      }
    >
      <ShoppingCart size={16} className="mr-1.5" />
      {isGenerating
        ? t("common:messages.loading")
        : t("recipes:meal_planner.generate_list")}
    </Button>
  );
}
