import { useTranslation } from "react-i18next";
import { Card } from "@/components/ui/Card";
import { formatQuantityLocalized } from "@/lib/i18nHelpers";
import { OrderMissingButton } from "@/modules/maker/components/OrderMissingButton";
import { ProductionCoverageBadge } from "@/modules/maker/components/ProductionCoverageBadge";
import type { ProductionOrder } from "@/modules/maker/types/maker";

/**
 * A draft run's place in the plan: whether the shelf still covers it after
 * the runs planned before it, which ingredients fall short of what is left for
 * it, and the one click that orders them.
 */
export function RunCoverageCard({ order }: { order: ProductionOrder }) {
  const { t } = useTranslation("maker");
  if (order.status !== "DRAFT" || !order.coverage) return null;
  const items = order.coverage_items ?? [];
  return (
    <Card className="p-4 space-y-3" data-testid="maker-run-coverage">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <h3 className="text-sm font-semibold text-on">
            {t("planning.coverage.title")}
          </h3>
          <ProductionCoverageBadge coverage={order.coverage} />
        </div>
        {order.coverage !== "covered" && (
          <OrderMissingButton scope={{ order_id: order.id }} />
        )}
      </div>
      <p className="text-xs text-on-secondary">
        {order.coverage === "covered"
          ? t("planning.coverage.coveredNote")
          : t("planning.coverage.shortNote")}
      </p>
      {items.length > 0 && (
        <ul className="divide-y divide-border text-sm">
          {items.map((item) => (
            <li
              key={item.child_template_id}
              className="flex justify-between gap-3 py-1.5"
            >
              <span className="text-on">{item.child_template_name}</span>
              <span className="text-on-secondary tabular-nums">
                {t("planning.coverage.leftOf", {
                  left: formatQuantityLocalized(
                    t,
                    item.available,
                    item.uom_symbol,
                  ),
                  needed: formatQuantityLocalized(
                    t,
                    item.needed,
                    item.uom_symbol,
                  ),
                })}
              </span>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}
