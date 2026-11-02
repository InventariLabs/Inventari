import { Calendar, ShoppingCart, Trash2, ChevronRight } from "lucide-react";
import { Link } from "react-router-dom";
import { Card } from "@/components/ui/Card";
import { Button, buttonVariants } from "@/components/ui/Button";
import { Badge } from "@/components/ui/Badge";
import { cn } from "@/lib/utils";
import { formatDateRange } from "@/utils/helpers";
import type { MealPlanListItem } from "@/modules/recipes/types/mealplans";

interface MealPlanCardProps {
  plan: MealPlanListItem;
  onDelete: (id: string) => void;
  onGenerateShoppingList: (id: string) => void;
  /** writing to a disabled shopping_lists module succeeded
   *  silently — hide the shopping actions when it is not enabled. */
  shoppingListsEnabled?: boolean;
  /** Whether to offer the actions that change the plan or write a list. */
  canWrite?: boolean;
  t: (key: string, opts?: Record<string, unknown>) => string;
}

export function MealPlanCard({
  plan,
  onDelete,
  onGenerateShoppingList,
  shoppingListsEnabled = true,
  canWrite = true,
  t,
}: MealPlanCardProps) {
  return (
    <Card className="p-4 flex flex-col gap-3">
      {/* the whole header + badges area navigates to the plan —
          only the card footer keeps its own buttons. */}
      <Link
        to={`/recipes/meal-planner/${plan.id}`}
        className="flex-1 min-w-0 group"
      >
        <div className="flex items-start justify-between gap-2">
          <div className="flex-1 min-w-0">
            <h3 className="font-semibold text-sm truncate group-hover:text-primary-600 transition-colors">
              {plan.name ?? t("recipes:meal_planner.unnamed_plan")}
            </h3>
            <div className="flex items-center gap-1.5 text-xs text-on-muted mt-1">
              <Calendar size={12} />
              <span>{formatDateRange(plan.start_date, plan.end_date)}</span>
            </div>
          </div>
          <ChevronRight
            size={18}
            className="text-on-muted group-hover:text-primary-600 group-hover:translate-x-0.5 transition-all duration-200"
          />
        </div>

        <div className="flex items-center gap-2 flex-wrap mt-3">
          <Badge variant="secondary" className="text-xs">
            {t("recipes:meal_planner.entry_count", { count: plan.entry_count })}
          </Badge>
          {plan.shopping_list_id && (
            <Badge variant="success" className="text-xs">
              <ShoppingCart size={10} className="mr-1" />
              {t("recipes:meal_planner.list_generated")}
            </Badge>
          )}
        </div>
      </Link>

      <div className="flex items-center gap-2 pt-1 border-t border-border">
        {shoppingListsEnabled &&
          (plan.shopping_list_id ? (
            <Link
              to={`/shopping-lists/${plan.shopping_list_id}`}
              className={cn(
                buttonVariants({ variant: "secondary", size: "sm" }),
                "flex-1",
              )}
            >
              <ShoppingCart size={14} />
              {t("recipes:meal_planner.view_shopping_list")}
            </Link>
          ) : (
            canWrite && (
              <Button
                variant="ghost"
                size="sm"
                className="flex-1 text-xs"
                onClick={() => onGenerateShoppingList(plan.id)}
                // A plan whose own badge reads "0 meals" has nothing to shop
                // for; the detail screen has always said so, the card did not.
                disabled={plan.entry_count === 0}
                title={
                  plan.entry_count === 0
                    ? t("recipes:meal_planner.generate_list_disabled_tooltip")
                    : undefined
                }
              >
                <ShoppingCart size={16} className="mr-1" />
                {t("recipes:meal_planner.generate_list")}
              </Button>
            )
          ))}
        {canWrite && (
          <Button
            variant="ghost"
            size="sm"
            className="text-on-danger hover:text-on-danger hover:bg-red-50 ml-auto"
            onClick={() => onDelete(plan.id)}
            aria-label={t("recipes:meal_planner.delete_plan")}
            title={t("recipes:meal_planner.delete_plan")}
          >
            <Trash2 size={16} aria-hidden="true" />
          </Button>
        )}
      </div>
    </Card>
  );
}
