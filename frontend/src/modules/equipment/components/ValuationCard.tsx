import { useTranslation } from "react-i18next";
import { TrendingDown, DollarSign, Clock } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/Card";
import { InfoRow } from "@/modules/equipment/components/AssetInfoRow";
import { useAssetValuation } from "@/modules/equipment/hooks/useValuation";
import { useOrganizationCurrency } from "@/hooks/useOrganizationCurrency";
import { formatMoney, formatPercentLocale } from "@/utils/formatters";

interface ValuationCardProps {
  itemId: string;
}

export function ValuationCard({ itemId }: ValuationCardProps) {
  const { t, i18n } = useTranslation("equipment");
  const currency = useOrganizationCurrency();
  const lang = i18n.language?.substring(0, 2) ?? "en";
  const { data: val, isLoading } = useAssetValuation(itemId);

  if (isLoading) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="text-sm">
            {t("valuation.title", "Valuation")}
          </CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-on-secondary">
            {t("valuation.loading", "Loading...")}
          </p>
        </CardContent>
      </Card>
    );
  }

  if (!val || !val.is_depreciable) return null;

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-sm">
          {t("valuation.title", "Valuation")}
        </CardTitle>
      </CardHeader>
      <CardContent>
        <InfoRow
          icon={<DollarSign size={14} />}
          label={t("valuation.purchase_price", "Purchase Price")}
          value={
            val.purchase_price != null
              ? formatMoney(val.purchase_price, currency, lang)
              : null
          }
        />
        <InfoRow
          icon={<DollarSign size={14} />}
          label={t("valuation.book_value", "Book Value")}
          value={formatMoney(val.book_value, currency, lang)}
        />
        <InfoRow
          icon={<TrendingDown size={14} />}
          label={t("valuation.depreciation", "Depreciation")}
          // The API reports tenths of a percent; the card keeps that digit
          // and writes it the way the reader's language does.
          value={formatPercentLocale(val.depreciation_pct, 1)}
        />
        <InfoRow
          icon={<Clock size={14} />}
          label={t("valuation.useful_life", "Useful Life")}
          value={t("valuation.years", "{{years}} years", {
            years: val.useful_life_years,
          })}
        />
      </CardContent>
    </Card>
  );
}
