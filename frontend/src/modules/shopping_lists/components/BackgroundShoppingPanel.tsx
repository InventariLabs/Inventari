import { useTranslation } from "react-i18next";
import { ShoppingCart } from "lucide-react";
import { QueryResult } from "@/components/ui/QueryResult";
import { EmptyState } from "@/components/ui/EmptyState";
import { useActiveShoppingList } from "../hooks/useShoppingLists";
import { formatQuantityValue } from "@/utils/formatters";
import { unitLabel } from "@/lib/i18nHelpers";

export default function BackgroundShoppingPanel() {
  const { t } = useTranslation(["shopping_lists", "common"]);
  const query = useActiveShoppingList();
  return (
    <QueryResult query={query} renderWhenEmpty>
      {(list) =>
        !list ? (
          <EmptyState
            variant="compact"
            icon={ShoppingCart}
            title={t("detail.empty")}
            description={t("detail.emptySubtitleRecipes")}
          />
        ) : (
          <div className="space-y-3">
            {/* The panel shows the first of possibly several active lists:
                the name is what says which one this is, empty or not. */}
            <p className="text-sm font-medium text-on">{list.name}</p>
            {list.items.length === 0 ? (
              <EmptyState
                variant="compact"
                icon={ShoppingCart}
                title={t("detail.empty")}
                description={t("detail.emptySubtitleRecipes")}
              />
            ) : (
              <table className="w-full text-left text-sm">
                <thead>
                  <tr className="border-b border-border text-on-secondary">
                    <th scope="col" className="py-2.5">
                      {t("addItem.nameLabel")}
                    </th>
                    <th scope="col" className="py-2.5 text-right">
                      {t("addItem.quantityLabel")}
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {list.items.map((item) => (
                    <tr
                      key={item.id}
                      className="border-b border-border last:border-0"
                    >
                      <td className="py-2.5 text-on">
                        {item.name}
                        {item.is_purchased && (
                          <span className="ml-2 text-on-muted">
                            {t("completed")}
                          </span>
                        )}
                      </td>
                      <td className="py-2.5 text-right tabular-nums text-on">
                        {formatQuantityValue(item.quantity, item.uom?.rounding)}{" "}
                        {unitLabel(t, item.uom?.symbol)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        )
      }
    </QueryResult>
  );
}
