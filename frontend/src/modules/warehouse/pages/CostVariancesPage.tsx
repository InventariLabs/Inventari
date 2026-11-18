import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { Card } from "@/components/ui/Card";
import LoadingSpinner from "@/components/LoadingSpinner";
import { QueryFailure } from "@/components/ui/QueryResult";
import { useMoney } from "@/hooks/useMoney";
import { formatDate } from "@/utils/formatters";
import { useCostVariances } from "@/modules/warehouse/hooks/useExtraCosts";

/**
 * Every delivery cost that reached no product, and what they add up to.
 *
 * The sums belong to no stock value: a variance is the figure and its reason,
 * not a ledger entry. They are kept per currency, because a variance is never
 * converted.
 */
export default function CostVariancesPage() {
  const { t } = useTranslation("warehouse");
  const money = useMoney();
  const { data, isLoading, isError, error, refetch } = useCostVariances();

  if (isError) {
    return (
      <QueryFailure
        error={error}
        message={t("costVariances.loadFailed")}
        onRetry={() => refetch()}
      />
    );
  }
  if (isLoading || !data) {
    return (
      <div className="flex justify-center py-20">
        <LoadingSpinner />
      </div>
    );
  }

  const totals = Object.entries(data.totals);

  return (
    <div className="space-y-4">
      <p className="text-sm text-on-secondary">
        {t("costVariances.notValued")}
      </p>

      {data.items.length === 0 ? (
        <Card className="p-6 text-sm text-on-secondary">
          {t("costVariances.empty")}
        </Card>
      ) : (
        <Card className="p-4 sm:p-5">
          <div className="overflow-x-auto">
            <table className="w-full text-left border-collapse text-sm">
              <thead>
                <tr className="border-b border-border text-xs font-medium text-on-secondary uppercase tracking-wider">
                  <th scope="col" className="py-2 pr-3">
                    {t("costVariances.columns.date")}
                  </th>
                  <th scope="col" className="py-2 px-3">
                    {t("costVariances.columns.document")}
                  </th>
                  <th scope="col" className="py-2 px-3">
                    {t("costVariances.columns.kind")}
                  </th>
                  <th scope="col" className="py-2 px-3">
                    {t("costVariances.columns.reason")}
                  </th>
                  <th scope="col" className="py-2 pl-3 text-right">
                    {t("costVariances.columns.amount")}
                  </th>
                </tr>
              </thead>
              <tbody>
                {data.items.map((item) => (
                  <tr
                    key={item.id}
                    className="border-b border-border last:border-0"
                  >
                    <td className="py-2 pr-3 text-on-secondary">
                      {formatDate(item.occurred_on)}
                    </td>
                    <td className="py-2 px-3">
                      <Link
                        to={`/warehouse/documents/${item.document_id}`}
                        className="text-primary-600 hover:underline"
                      >
                        {item.document_number ?? "—"}
                      </Link>
                    </td>
                    <td className="py-2 px-3 text-on">
                      {t(`extraCosts.kind.${item.kind}`, {
                        defaultValue: item.kind,
                      })}
                    </td>
                    <td className="py-2 px-3 text-on">{item.reason}</td>
                    <td className="py-2 pl-3 text-right tabular-nums text-on">
                      {money(Number(item.amount), item.currency)}
                    </td>
                  </tr>
                ))}
              </tbody>
              <tfoot>
                {totals.map(([currency, total]) => (
                  <tr key={currency} className="font-medium text-on">
                    <th
                      scope="row"
                      colSpan={4}
                      className="pt-3 pr-3 text-right text-sm"
                    >
                      {t("costVariances.total")}
                    </th>
                    <td className="pt-3 pl-3 text-right tabular-nums">
                      {money(Number(total), currency || null)}
                    </td>
                  </tr>
                ))}
              </tfoot>
            </table>
          </div>
        </Card>
      )}
    </div>
  );
}
