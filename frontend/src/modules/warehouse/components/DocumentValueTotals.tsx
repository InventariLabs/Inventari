import { useTranslation } from "react-i18next";
import { Card } from "@/components/ui/Card";
import { useDocumentCurrency } from "@/hooks/useDocumentCurrency";
import { useShowDocumentValue } from "@/modules/warehouse/hooks/useShowDocumentValue";
import type { WarehouseDocument } from "@/modules/warehouse/types";
import { formatMoney, formatPercentLocale } from "@/utils/formatters";
import { amountsByRate } from "@/utils/money";

interface DocumentValueTotalsProps {
  document: WarehouseDocument;
}

/**
 * Lines of a posted receipt that came in with no price, as a product added on
 * a phone does: the document's totals leave them out and the stock has no
 * recorded cost, which the totals alone do not say.
 */
function hasReceivedLineWithoutPrice(document: WarehouseDocument): boolean {
  return (
    document.status === "COMPLETED" &&
    ["IN", "INTERNAL_IN"].includes(document.type) &&
    (document.lines ?? []).some((line) => line.unit_price == null)
  );
}

export function DocumentValueTotals({ document }: DocumentValueTotalsProps) {
  const { t, i18n } = useTranslation("warehouse");
  const currency = useDocumentCurrency(document.currency);
  const showValue = useShowDocumentValue(document.type);
  const isScrap = document.type === "SCRAP";

  // A document whose screens never offer a price owes the reader no
  // totals: the figures are stored and registered either way. A write-off is
  // the exception that proves it: nobody types its value, the cost layers it
  // drew do, and the loss is worth stating where the document is read.
  if (isScrap && document.total_net != null) {
    return (
      <Card className="overflow-hidden">
        <div className="px-4 sm:px-6 py-4">
          <div className="flex items-center justify-between text-sm font-semibold">
            <span className="text-on">{t("value.scrapCost")}</span>
            <span className="font-mono text-on">
              {formatMoney(document.total_net, currency, i18n.language)}
            </span>
          </div>
        </div>
      </Card>
    );
  }
  const unpriced = hasReceivedLineWithoutPrice(document);
  if (!showValue) return null;
  if (!document.total_gross && !document.total_net) {
    return unpriced ? (
      <Card className="px-4 sm:px-6 py-4 text-sm text-on-secondary">
        {t("value.unpricedLines")}
      </Card>
    ) : null;
  }
  // Goods at a reduced rate next to goods at the standard one: the tax per
  // rate, which the totals alone do not say. One rate would repeat them.
  const byRate = amountsByRate(document.lines ?? []);

  return (
    <Card className="overflow-hidden">
      <div className="px-4 sm:px-6 py-3 border-b border-border">
        <h2 className="font-medium text-on text-sm">
          {t("value.totalsTitle")}
        </h2>
      </div>
      <div className="px-4 sm:px-6 py-4">
        <dl className="space-y-2">
          <div className="flex items-center justify-between text-sm">
            <dt className="text-on-secondary">{t("value.totalNet")}</dt>
            <dd className="font-mono font-medium text-on">
              {formatMoney(document.total_net, currency, i18n.language)}
            </dd>
          </div>
          {document.total_tax !== null && document.total_tax !== undefined && (
            <div className="flex items-center justify-between text-sm">
              <dt className="text-on-secondary">{t("value.totalTax")}</dt>
              <dd className="font-mono text-on">
                {formatMoney(document.total_tax, currency, i18n.language)}
              </dd>
            </div>
          )}
          <div className="flex items-center justify-between border-t border-border pt-2 text-sm font-semibold">
            <dt className="text-on">{t("value.totalGross")}</dt>
            <dd className="font-mono text-on">
              {formatMoney(document.total_gross, currency, i18n.language)}
            </dd>
          </div>
        </dl>
        {unpriced && (
          <p className="mt-3 text-sm text-on-secondary">
            {t("value.unpricedLines")}
          </p>
        )}
        {byRate.length > 1 && (
          <table className="mt-4 w-full border-t border-border pt-3 text-sm">
            <caption className="text-left text-xs font-medium text-on-secondary pb-1">
              {t("value.byRateTitle")}
            </caption>
            <thead>
              <tr className="text-xs text-on-secondary">
                <th scope="col" className="text-left font-normal">
                  {t("value.byRateRate")}
                </th>
                <th scope="col" className="text-right font-normal">
                  {t("value.totalNet")}
                </th>
                <th scope="col" className="text-right font-normal">
                  {t("value.totalTax")}
                </th>
              </tr>
            </thead>
            <tbody>
              {byRate.map((row) => (
                <tr key={row.rate}>
                  <th scope="row" className="text-left font-normal text-on">
                    {/* As a string, the rate keeps its own digits: 5.5%, not 6%. */}
                    {formatPercentLocale(String(row.rate), 0, i18n.language)}
                  </th>
                  <td className="text-right font-mono text-on">
                    {formatMoney(row.net, currency, i18n.language)}
                  </td>
                  <td className="text-right font-mono text-on">
                    {formatMoney(row.tax, currency, i18n.language)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </Card>
  );
}
