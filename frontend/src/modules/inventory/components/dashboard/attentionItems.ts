import type { TFunction } from "i18next";
import type { Item, LowStockProduct } from "@/types";
import type { AttentionItem } from "@/module-sdk";
import { formatDate, formatDecimalQty } from "@/utils/formatters";
import { formatQuantityLocalized } from "@/lib/i18nHelpers";
import { quantityText } from "@/modules/shared/hooks/usePartialPackage";
import type { PartialPackage } from "@/utils/partialPackage";
import type { AttentionGroup } from "@/modules/inventory/hooks/useDashboardAttention";

/**
 * The attention card's rows for the inventory overview. A row opens its
 * record in the products list, the same drawer the list itself opens.
 */
export function toAttentionItems(
  groups: readonly AttentionGroup[],
  locations: ReadonlyMap<string, { name: string }>,
  lowProducts: readonly LowStockProduct[],
  t: TFunction,
  partialOf: (item: Item) => PartialPackage | null,
): AttentionItem[] {
  const dated = groups.map((group) => {
    const first = group.items[0];
    const where = locations.get(first.location_id)?.name;
    // The date is why the row is here, and on a phone it sits far down the
    // sheet, so the link asks for it.
    const href = `/inventory/items?open=${first.id}&at=expiry`;
    const date = formatDate(first.expiry_date);
    // A product held as two records (half a carton left after cooking) is
    // two rows; the quantity is what tells them apart, read the way the
    // products list reads it ("0.5 l left of 1 l", not "0.5 pcs.").
    const quantity = quantityText(t, first, partialOf(first));
    return {
      id: group.key,
      severity: group.kind,
      title: first.name,
      reason:
        group.kind === "expired"
          ? t("common:dashboard.attention.expired", { date, quantity })
          : t("common:dashboard.attention.expiring", { date, quantity }),
      where,
      href,
    };
  });
  return [...dated, ...lowProducts.map((product) => lowStockRow(product, t))];
}

/**
 * A short product is one row about the product, not about a record: what is
 * on the shelf against the minimum. A product with nothing left says so, and
 * never says where the last record went — that is bookkeeping, not an answer.
 */
function lowStockRow(product: LowStockProduct, t: TFunction): AttentionItem {
  const minimum = formatQuantityLocalized(
    t,
    formatDecimalQty(String(product.minimum)),
    product.uom_symbol,
  );
  const reason =
    product.on_hand > 0
      ? t("common:dashboard.attention.low", {
          quantity: formatQuantityLocalized(
            t,
            formatDecimalQty(String(product.on_hand)),
            product.uom_symbol,
          ),
          minimum,
        })
      : t("common:dashboard.attention.out", { minimum });
  return {
    id: `low:${product.template_id}`,
    severity: "low",
    title: product.name,
    reason,
    // Used up or not, the product has its page; only a product with no
    // record at all falls back to the list.
    href: product.item_id
      ? `/inventory/items/${product.item_id}`
      : "/inventory/items",
  };
}
