import { useTranslation } from "react-i18next";
import { useMoney } from "@/hooks/useMoney";
import { formatDate } from "@/utils/formatters";
import { Card, CardContent } from "@/components/ui/Card";
import { ProductCombobox } from "@/components/ui/ProductCombobox";
import type { CatalogueSearchResult } from "@/modules/warehouse/moduleApi";
import type { PartnerPricelist } from "../api/pricelist";

interface PricelistComparisonCardProps {
  /** The product being compared, once one is picked. */
  compareProduct: CatalogueSearchResult | null;
  entries: PartnerPricelist[];
  /** Supplier names by partner id; an id with no name prints as the id. */
  supplierNames: ReadonlyMap<string, string>;
  /**
   * Product search for the picker. The page owns the concrete API so the card
   * stays vocabulary-free.
   */
  searchProducts: (q: string) => Promise<CatalogueSearchResult[]>;
  onSelect: (product: CatalogueSearchResult) => void;
  onClear: () => void;
}

export function PricelistComparisonCard({
  compareProduct,
  entries,
  supplierNames,
  searchProducts,
  onSelect,
  onClear,
}: PricelistComparisonCardProps) {
  const { t } = useTranslation("purchase_orders");
  // A pricelist entry carries a supplier's own currency, which wins
  // over the organization default.
  const money = useMoney();

  return (
    <Card>
      <CardContent className="p-5">
        {/* Title, the control it belongs to, and what the card will show once
            it has an answer — the field used to sit under a bare heading with
            the rest of the card empty around it. */}
        <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
          <div className="min-w-0">
            <h2 className="text-sm font-medium text-on">
              {t("pricelist.comparisonTitle")}
            </h2>
            <p className="mt-0.5 text-sm text-on-muted">
              {t("pricelist.comparisonSubtitle")}
            </p>
            {/* the picker searches product templates only, while an
                order can carry a free-text ad-hoc line. Say the limit instead
                of letting a fresh org search for the very line it just typed. */}
            <p className="mt-0.5 text-xs text-on-muted">
              {t("pricelist.comparisonCatalogOnly")}
            </p>
          </div>
          <div className="w-full sm:w-72 sm:shrink-0">
            <ProductCombobox
              label={t("productPicker.search")}
              value={compareProduct}
              onSelect={onSelect}
              onClear={onClear}
              search={searchProducts}
              placeholder={t("productPicker.search")}
            />
          </div>
        </div>
        {compareProduct && entries.length === 0 && (
          <p className="py-6 text-center text-sm text-on-muted">
            {t("pricelist.comparisonEmpty")}
          </p>
        )}
        {compareProduct && entries.length > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-surface-inset text-left text-xs uppercase tracking-wide text-on-muted">
                  <th scope="col" className="px-4 py-2">
                    {t("pricelist.supplier")}
                  </th>
                  <th scope="col" className="px-4 py-2">
                    {t("pricelist.price")}
                  </th>
                  <th scope="col" className="px-4 py-2">
                    {t("pricelist.validity")}
                  </th>
                </tr>
              </thead>
              <tbody>
                {entries
                  .slice()
                  .sort((a, b) => Number(a.unit_price) - Number(b.unit_price))
                  .map((entry) => {
                    return (
                      <tr
                        key={entry.id}
                        className="border-b border-surface-inset/60 last:border-0"
                      >
                        <td className="px-4 py-2">
                          {supplierNames.get(entry.partner_id) ??
                            entry.partner_id}
                        </td>
                        <td className="px-4 py-2 font-medium">
                          {money(entry.unit_price, entry.currency)}
                        </td>
                        <td className="px-4 py-2 text-on-secondary">
                          {formatDate(entry.valid_from)}
                          {entry.valid_to
                            ? ` → ${formatDate(entry.valid_to)}`
                            : ` → ${t("common:datePicker.empty")}`}
                        </td>
                      </tr>
                    );
                  })}
              </tbody>
            </table>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
