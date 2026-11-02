import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import { BarChart3 } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/Card";
import LoadingSpinner from "@/components/LoadingSpinner";
import { QueryFailure } from "@/components/ui/QueryResult";
import { useFleetValuation } from "@/modules/equipment/hooks/useValuation";
import { useOrganizationCurrency } from "@/hooks/useOrganizationCurrency";
import { getCategoryLabel } from "@/modules/equipment/components/assetUtils";
import { formatMoney } from "@/utils/formatters";
import { cn } from "@/lib/utils";

export function FleetValuationWidget() {
  const { t, i18n } = useTranslation("equipment");
  const currency = useOrganizationCurrency();
  const lang = i18n.language?.substring(0, 2) ?? "en";
  const { data: val, isLoading, isError, error, refetch } = useFleetValuation();

  if (isLoading) return <LoadingSpinner />;
  if (isError)
    return <QueryFailure error={error} onRetry={() => void refetch()} />;
  if (!val || (val.asset_count === 0 && val.excluded_count === 0)) return null;

  // Book value and depreciation are conditional: they exist only for the
  // assets configured with a purchase date and a useful life.
  // When nothing is configured the widget shows purchase value alone —
  // a zero would be a claim nobody entered — and when only some assets are
  // configured, the financial columns stay but the unconfigured ones are
  // named and a category with none shows a dash, not 0.00.
  const showFinance = val.depreciable_count > 0;
  const unconfigured = val.asset_count - val.depreciable_count;

  return (
    // min-w-0 lets the card take the zero-min grid track's width on a phone
    // instead of forcing the track out to the table's min-content.
    <Card className="min-w-0">
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-sm">
          <BarChart3 size={16} />
          {t("valuation.fleet_title", "Fleet Valuation")}
        </CardTitle>
      </CardHeader>
      <CardContent>
        {(val.no_status_count ?? 0) > 0 && (
          <div className="text-xs text-on-secondary mb-3">
            <p>
              {t("valuation.no_status_note", { count: val.no_status_count })}
            </p>
            <ul>
              {(val.no_status_assets ?? []).map((asset) => (
                <li key={asset.id}>
                  <Link to={`/equipment/${asset.id}`}>{asset.name}</Link>
                </li>
              ))}
            </ul>
          </div>
        )}
        {val.excluded_count > 0 && (
          <p className="text-xs text-on-muted mb-3">
            {t("valuation.excluded_note", { count: val.excluded_count })}
          </p>
        )}
        {showFinance && unconfigured > 0 && (
          <p className="text-xs text-on-muted mb-3">
            {t("valuation.undepreciated_note", { count: unconfigured })}
          </p>
        )}
        {!showFinance && (
          <p className="text-xs text-on-muted mb-3">
            {t(
              "valuation.depreciation_off_note",
              "Book value and depreciation appear for assets with a purchase date and useful life.",
            )}
          </p>
        )}
        <div
          className={cn(
            "grid gap-4 mb-4",
            showFinance ? "grid-cols-1 sm:grid-cols-3" : "grid-cols-1",
          )}
        >
          <div className="text-center">
            <div className="text-lg font-semibold text-on">
              {formatMoney(val.total_purchase_value, currency, lang)}
            </div>
            <div className="text-xs text-on-secondary">
              {t("valuation.total_purchase", "Purchase Value")}
            </div>
          </div>
          {showFinance && (
            <>
              <div className="text-center">
                <div className="text-lg font-semibold text-on-success">
                  {formatMoney(val.total_book_value, currency, lang)}
                </div>
                <div className="text-xs text-on-secondary">
                  {t("valuation.total_book", "Book Value")}
                </div>
              </div>
              <div className="text-center">
                <div className="text-lg font-semibold text-on-warning">
                  {formatMoney(val.total_depreciation, currency, lang)}
                </div>
                <div className="text-xs text-on-secondary">
                  {t("valuation.total_depreciation", "Depreciation")}
                </div>
              </div>
            </>
          )}
        </div>

        {val.by_category.length > 0 && (
          <div className="space-y-2">
            <div className="text-xs font-medium text-on-muted uppercase tracking-wider">
              {t("valuation.by_category", "By Category")}
            </div>
            {/* The card fits the phone; the table scrolls inside it. The
                cells also carry horizontal padding so two right-aligned
                numbers can never share an edge and read as one amount. */}
            {/* `relative` contains the sr-only spans the dash cells carry:
                `sr-only` is absolute, and without a positioned scroller it
                escapes the card and widens the page. */}
            <div className="overflow-x-auto relative">
              <table className="w-full text-xs sm:text-sm">
                <thead>
                  <tr className="text-xs text-on-muted border-b border-border">
                    <th className="text-left py-1 px-1 sm:px-2 first:pl-0">
                      {t("valuation.category", "Category")}
                    </th>
                    <th className="text-right py-1 px-1 sm:px-2 last:pr-0 break-words hyphens-auto">
                      {/* "Valued", not "Count": this column counts the assets
                          that carry value here — retired, priceless and
                          foreign-currency ones are left out, and the register's
                          count (the categories catalogue) reads higher. */}
                      {t("valuation.countValued", "Valued")}
                    </th>
                    {showFinance && (
                      <>
                        <th className="text-right py-1 px-1 sm:px-2 break-words hyphens-auto">
                          {t("valuation.book_value", "Book Value")}
                        </th>
                        <th className="text-right py-1 px-1 sm:px-2 last:pr-0 break-words hyphens-auto">
                          {t("valuation.depreciation", "Depreciation")}
                        </th>
                      </>
                    )}
                  </tr>
                </thead>
                <tbody>
                  {val.by_category.map((cat) => (
                    <tr
                      key={cat.category_name}
                      className="border-b border-border/50 last:border-0"
                    >
                      <td className="py-1.5 pl-0 pr-1 sm:pr-2 text-on break-words hyphens-auto">
                        {getCategoryLabel(t, {
                          code: cat.category_code,
                          name: cat.category_name,
                        })}
                      </td>
                      <td className="py-1.5 px-1 sm:px-2 text-right text-on-secondary tabular-nums">
                        {cat.asset_count}
                      </td>
                      {showFinance && (
                        <>
                          <td className="py-1.5 px-1 sm:px-2 text-right font-medium text-on-success tabular-nums">
                            {cat.depreciable_count > 0 ? (
                              formatMoney(cat.book_value, currency, lang)
                            ) : (
                              <NoFigure
                                label={t(
                                  "valuation.not_configured",
                                  "Not configured",
                                )}
                              />
                            )}
                          </td>
                          <td className="py-1.5 pl-1 sm:pl-2 pr-0 text-right text-on-warning tabular-nums">
                            {cat.depreciable_count > 0 ? (
                              formatMoney(cat.depreciation, currency, lang)
                            ) : (
                              <NoFigure
                                label={t(
                                  "valuation.not_configured",
                                  "Not configured",
                                )}
                              />
                            )}
                          </td>
                        </>
                      )}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

/** A financial cell with no configuration behind it: a dash on the screen,
 * and a sentence for anyone who cannot see it. */
function NoFigure({ label }: { label: string }) {
  return (
    <>
      <span aria-hidden="true">—</span>
      <span className="sr-only">{label}</span>
    </>
  );
}
