import { useTranslation } from "react-i18next";
import { useMoney } from "@/hooks/useMoney";
import { useShowInventoryValue } from "@/modules/shared/hooks/useShowInventoryValue";
import { formatNumberLocale } from "@/utils/formatters";
import type { ItemAggregates } from "@/types";

type Props = {
  aggregates: ItemAggregates | undefined;
};

/**
 * Sums over the whole filtered set — not over the page on screen.
 *
 * The list paginates server-side, so adding up the visible rows would
 * contradict itself the moment the reader turns the page. These numbers come
 * from /items/aggregates with the same filters the list applied, so the
 * footer and the rows can never disagree.
 *
 * Zero weight or value hides its figure — an organization that weighs or
 * prices nothing gets no "0.0 kg" noise. The count always stands.
 *
 * Weight and volume stand in two figures, each under its own unit: the API
 * sums kilograms and litres apart, and one figure labelled kg read 2 l of
 * milk as 2 kg. A litre-only list therefore shows its litres and no
 * kilogram total.
 *
 * The value is read where "Stock on a date" and the statistics read it —
 * the cost ledger, where the organization keeps one. A filtered view gets
 * no ledger figure at all: the layers know products, not shelves, so the
 * ledger holds no value for a slice, and the footer says that instead of
 * showing a number priced at rates other shelves earned. Rows the sum
 * could not price are named beside the figure, the way the stock-as-of
 * report names them: a total that quietly summed them as nothing said
 * "worth 0.00" about stock nobody had valued.
 *
 * Where the profile does not show stock value (`show_inventory_value`),
 * even that explanation goes: a home organization keeps no prices, and
 * "cost layers" and "filtered slice" are the first accounting words on a
 * shopping list. The count and the weight still describe the slice.
 */
export default function ItemsTotalsFooter({ aggregates }: Props) {
  const { t } = useTranslation("items");
  const money = useMoney();
  const showInventoryValue = useShowInventoryValue();

  if (!aggregates || aggregates.count === 0) return null;
  // The switch, not the API, decides whether a figure is offered at all:
  // a profile that does not show stock value reads as "none", and every
  // sentence below that explains a figure silences with it. The
  // withheld-under-filter note keeps its own condition — it must not stand
  // in for the switch.
  const totalValue = showInventoryValue ? aggregates.total_value : null;

  return (
    <div className="flex flex-wrap items-center justify-end gap-x-4 gap-y-1 px-3 sm:px-4 py-2.5 bg-surface-card rounded-xl border border-border">
      <span className="text-[10px] font-medium uppercase tracking-widest text-on-muted mr-auto">
        {t("totals.label")}
      </span>
      <span className="text-sm text-on-secondary tabular-nums">
        {t("totals.positions", { count: aggregates.count })}
      </span>
      {aggregates.total_weight > 0 && (
        <span className="text-sm text-on-secondary tabular-nums">
          {t("totals.weight", {
            weight: formatNumberLocale(aggregates.total_weight, 1),
          })}
        </span>
      )}
      {aggregates.total_volume > 0 && (
        <span className="text-sm text-on-secondary tabular-nums">
          {t("totals.volume", {
            volume: formatNumberLocale(aggregates.total_volume, 1),
          })}
        </span>
      )}
      {showInventoryValue && totalValue == null && (
        <span className="basis-full text-right text-xs text-on-muted">
          {t("totals.valueUnavailableUnderFilter")}
        </span>
      )}
      {totalValue != null && totalValue > 0 && (
        <span className="text-sm font-medium text-on tabular-nums">
          {money(totalValue)}
        </span>
      )}
      {totalValue != null && aggregates.unpriced_count > 0 && (
        <span className="basis-full text-right text-xs text-on-muted">
          {t("totals.unpriced", { count: aggregates.unpriced_count })}
        </span>
      )}
      {totalValue != null && aggregates.excludes_module_items && (
        <span className="basis-full text-right text-xs text-on-muted">
          {t("totals.moduleSlice")}
        </span>
      )}
      {totalValue != null && aggregates.excludes_unlisted_layers && (
        <span className="basis-full text-right text-xs text-on-muted">
          {t("totals.unlistedLayers")}
        </span>
      )}
    </div>
  );
}
