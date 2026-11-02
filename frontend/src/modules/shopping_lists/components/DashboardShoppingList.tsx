import { Link } from "react-router-dom";
import { Plus } from "lucide-react";
import type { ShoppingListItem } from "@/modules/shopping_lists/types/shopping";
import { Card, CardHeader, CardTitle } from "@/components/ui/Card";
import { CardLink, CompositionBar } from "@/module-sdk";

interface DashboardShoppingListProps {
  activeShoppingList: {
    id: string;
    name?: string | null;
    items?: ShoppingListItem[];
  } | null;
  t: (key: string, opts?: Record<string, unknown>) => string;
}

/**
 * The active shopping list as one line of progress: its name, how much of
 * it is already in the basket, and the count. The list itself is one click
 * away — the overview answers "how far along", not "what exactly".
 */
export default function DashboardShoppingList({
  activeShoppingList,
  t,
}: DashboardShoppingListProps) {
  return (
    <Card className="p-4 sm:p-5">
      <CardHeader className="flex-row items-baseline justify-between space-y-0 pb-2">
        <CardTitle>{t("common:dashboard.shoppingList")}</CardTitle>
        <CardLink to="/shopping-lists" arrow className="text-xs">
          {t("common:dashboard.manage")}
        </CardLink>
      </CardHeader>

      {activeShoppingList ? (
        <ListProgress list={activeShoppingList} t={t} />
      ) : (
        <div className="flex flex-wrap items-center justify-between gap-3 py-2.5">
          <p className="text-sm text-on-secondary">
            {t("common:dashboard.noActiveLists")}
          </p>
          <CardLink to="/shopping-lists" className="text-sm">
            <Plus size={16} aria-hidden="true" />
            {t("common:dashboard.createList")}
          </CardLink>
        </div>
      )}
    </Card>
  );
}

function ListProgress({
  list,
  t,
}: {
  list: NonNullable<DashboardShoppingListProps["activeShoppingList"]>;
  t: DashboardShoppingListProps["t"];
}) {
  const items = list.items ?? [];
  const total = items.length;
  const bought = items.filter((i) => i.is_purchased).length;
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-2 py-2.5">
      <Link
        to={`/shopping-lists/${list.id}`}
        className="min-h-6 min-w-0 flex-1 truncate text-sm font-semibold text-on hover:underline sm:w-40 sm:flex-none"
      >
        {list.name}
      </Link>
      <div className="order-last basis-full sm:order-none sm:basis-0 sm:flex-1">
        <CompositionBar
          count={bought}
          maxCount={total}
          segments={[{ key: "bought", count: bought, tone: "success" }]}
          ariaLabel={t("common:dashboard.shoppingProgress", {
            count: total,
            bought,
          })}
        />
      </div>
      <span className="shrink-0 text-right text-xs tabular-nums text-on-muted">
        {bought}/{total}
      </span>
    </div>
  );
}
