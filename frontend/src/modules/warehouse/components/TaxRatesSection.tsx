import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Plus, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Card, CardContent } from "@/components/ui/Card";
import { Input } from "@/components/ui/Input";
import { NativeSelect } from "@/components/ui/NativeSelect";
import { useCanManage } from "@/hooks/useCanWrite";
import { useScopedCategories } from "@/modules/shared/hooks/useCategories";
import { useCountryTaxRates } from "@/modules/warehouse/hooks/useTaxRates";
import {
  sameRate,
  useTaxRatesDraft,
  type CategoryRow,
  type RateRow,
} from "@/modules/warehouse/hooks/useTaxRatesDraft";
import { formatPercentLocale } from "@/utils/formatters";
import { SettingsSectionHeader } from "./SettingsSectionHeader";

type Draft = ReturnType<typeof useTaxRatesDraft>;

// The rate goes in as the string it is written as, so its own digits are
// printed: "5.50" reads 5.5%, where a number at no places read 6%.
const rateLabel = (row: RateRow, lang: string) =>
  row.name.trim() || formatPercentLocale(row.rate, 0, lang);

/** The country's rates the table does not hold yet, as rows to add. */
function useMissingCountryRates(rows: RateRow[]) {
  const { data, isError } = useCountryTaxRates();
  const missing = (data?.rates ?? []).filter(
    (offer) => !rows.some((row) => sameRate(row.rate, offer.rate)),
  );
  return { country: data?.country ?? null, missing, offerFailed: isError };
}

function RateRows({ d, canManage }: { d: Draft; canManage: boolean }) {
  const { t, i18n } = useTranslation("warehouse");
  const [next, setNext] = useState(0);
  const rows = d.rates ?? [];
  const { country, missing, offerFailed } = useMissingCountryRates(rows);
  const edit = (key: string, change: Partial<RateRow>) =>
    d.setRates(rows.map((r) => (r.key === key ? { ...r, ...change } : r)));
  const add = (added: Omit<RateRow, "key">[]) => {
    d.setRates([
      ...rows,
      ...added.map((row, i) => ({ ...row, key: `new-${next + i}` })),
    ]);
    setNext(next + added.length);
  };
  const remove = (key: string) => {
    d.setRates(rows.filter((r) => r.key !== key));
    d.setCategories((d.categories ?? []).filter((c) => c.rateKey !== key));
  };

  return (
    <div className="space-y-3">
      {rows.length === 0 && (
        <p className="text-sm text-on-secondary">{t("taxRates.none")}</p>
      )}
      {rows.map((row) => (
        <div
          key={row.key}
          className="grid grid-cols-[1fr_6rem_auto] items-end gap-2"
        >
          <Input
            label={t("taxRates.name")}
            value={row.name}
            maxLength={100}
            required
            onChange={(e) => edit(row.key, { name: e.target.value })}
          />
          <Input
            label={t("taxRates.rate")}
            type="number"
            min={0}
            max={100}
            step={0.01}
            required
            value={row.rate}
            onChange={(e) => edit(row.key, { rate: e.target.value })}
            rightIcon={<span className="text-xs font-medium">%</span>}
          />
          {canManage && (
            <Button
              variant="ghostDanger"
              size="icon"
              aria-label={t("taxRates.remove", {
                rate: rateLabel(row, i18n.language),
              })}
              onClick={() => remove(row.key)}
            >
              <Trash2 size={16} />
            </Button>
          )}
        </div>
      ))}
      {canManage && (
        <div className="flex flex-wrap gap-2">
          <Button
            variant="outline"
            size="sm"
            leftIcon={<Plus size={16} />}
            onClick={() => add([{ name: "", rate: "" }])}
          >
            {t("taxRates.add")}
          </Button>
          {offerFailed && (
            <p className="w-full text-xs text-on-secondary">
              {t("taxRates.countryLoadFailed")}
            </p>
          )}
          {country && missing.length > 0 && (
            <Button
              variant="outline"
              size="sm"
              onClick={() =>
                add(missing.map((o) => ({ name: o.name, rate: o.rate })))
              }
            >
              {t("taxRates.addCountry", {
                rates: missing
                  .map((o) => formatPercentLocale(o.rate, 0, i18n.language))
                  .join(", "),
              })}
            </Button>
          )}
        </div>
      )}
    </div>
  );
}

function CategoryRows({ d, canManage }: { d: Draft; canManage: boolean }) {
  const { t, i18n } = useTranslation("warehouse");
  const { all, scoped } = useScopedCategories();
  const [next, setNext] = useState(0);
  const rows = d.categories ?? [];
  const rates = (d.rates ?? []).filter((r) => r.rate !== "");
  const edit = (key: string, change: Partial<CategoryRow>) =>
    d.setCategories(rows.map((r) => (r.key === key ? { ...r, ...change } : r)));
  const taken = new Set(rows.map((r) => r.categoryId));
  const name = (id: string) => all?.find((c) => c.id === id)?.name ?? "—";
  // Another row is offered only while a category is left to name.
  const free = (scoped ?? []).filter((c) => !taken.has(c.id));

  return (
    <div className="space-y-3">
      {rows.length === 0 && (
        <p className="text-sm text-on-secondary">
          {t("taxRates.categoriesNone")}
        </p>
      )}
      {rows.map((row) => (
        <div
          key={row.key}
          className="grid grid-cols-[1fr_1fr_auto] items-end gap-2"
        >
          <NativeSelect
            label={t("taxRates.category")}
            value={row.categoryId}
            onChange={(e) => edit(row.key, { categoryId: e.target.value })}
          >
            <option value="">—</option>
            {(scoped ?? [])
              .filter((c) => c.id === row.categoryId || !taken.has(c.id))
              .map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
          </NativeSelect>
          <NativeSelect
            label={t("taxRates.categoryRate")}
            value={row.rateKey}
            onChange={(e) => edit(row.key, { rateKey: e.target.value })}
          >
            <option value="">—</option>
            {rates.map((r) => (
              <option key={r.key} value={r.key}>
                {rateLabel(r, i18n.language)}
              </option>
            ))}
          </NativeSelect>
          {canManage && (
            <Button
              variant="ghostDanger"
              size="icon"
              aria-label={t("taxRates.categoryRemove", {
                category: name(row.categoryId),
              })}
              onClick={() =>
                d.setCategories(rows.filter((r) => r.key !== row.key))
              }
            >
              <Trash2 size={16} />
            </Button>
          )}
        </div>
      ))}
      {canManage && rates.length > 0 && free.length > 0 && (
        <Button
          variant="outline"
          size="sm"
          leftIcon={<Plus size={16} />}
          onClick={() => {
            d.setCategories([
              ...rows,
              { key: `new-${next}`, categoryId: "", rateKey: "" },
            ]);
            setNext(next + 1);
          }}
        >
          {t("taxRates.categoryAdd")}
        </Button>
      )}
    </div>
  );
}

/**
 * The organization's tax rates, and the categories whose goods take one.
 *
 * A new document or order line takes the rate its product names (on the
 * product's own form), else its category's (here), else the default above.
 * The rows are a draft the page's Save writes, like every section around it.
 */
export function TaxRatesSection() {
  const { t } = useTranslation("warehouse");
  const canManage = useCanManage("warehouse");
  const d = useTaxRatesDraft();

  if (d.isError) {
    return (
      <section>
        <SettingsSectionHeader
          title={t("taxRates.title")}
          hint={t("taxRates.hint")}
        />
        <div className="flex items-center gap-3">
          <p className="text-sm text-on-secondary">
            {t("taxRates.loadFailed")}
          </p>
          <Button variant="outline" size="sm" onClick={d.refetch}>
            {t("common:actions.retry")}
          </Button>
        </div>
      </section>
    );
  }
  if (d.rates === null || d.categories === null) return null;

  return (
    <section className="space-y-6">
      <div>
        <SettingsSectionHeader
          title={t("taxRates.title")}
          hint={t("taxRates.hint")}
        />
        <Card>
          <CardContent className="p-4 sm:p-6">
            <RateRows d={d} canManage={canManage} />
          </CardContent>
        </Card>
      </div>
      <div>
        <SettingsSectionHeader
          title={t("taxRates.categoriesTitle")}
          hint={t("taxRates.categoriesHint")}
        />
        <Card>
          <CardContent className="p-4 sm:p-6">
            <CategoryRows d={d} canManage={canManage} />
          </CardContent>
        </Card>
      </div>
    </section>
  );
}
