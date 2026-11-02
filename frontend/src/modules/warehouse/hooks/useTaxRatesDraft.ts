import { useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { queryKeys } from "@/hooks/queries/keys";
import { usePageSavePart } from "@/module-sdk";
import {
  taxRatesApi,
  type CategoryTaxRate,
  type TaxRate,
} from "@/modules/warehouse/api/taxRates";
import {
  useCategoryTaxRates,
  useTaxRates,
} from "@/modules/warehouse/hooks/useTaxRates";

/** One rate as the form holds it; `id` is absent until it is saved. */
export interface RateRow {
  key: string;
  id?: string;
  name: string;
  rate: string;
}

/** One category naming a rate, by the key of the rate's row. */
export interface CategoryRow {
  key: string;
  categoryId: string;
  rateKey: string;
}

/** The number a rate is, so "7", "7.0" and "7.00" are one rate. */
export const sameRate = (a: string, b: string) => Number(a) === Number(b);

const toRateRows = (rates: TaxRate[]): RateRow[] =>
  rates.map((r) => ({ key: r.id, id: r.id, name: r.name, rate: r.rate }));

const toCategoryRows = (rows: CategoryTaxRate[]): CategoryRow[] =>
  rows.map((r) => ({
    key: r.category_id,
    categoryId: r.category_id,
    rateKey: r.tax_rate_id,
  }));

const rateChanged = (row: RateRow, saved: TaxRate | undefined) =>
  !saved || row.name.trim() !== saved.name || !sameRate(row.rate, saved.rate);

/** A category row the reader has not finished is not part of the draft. */
const complete = (rows: CategoryRow[]) =>
  rows.filter((row) => row.categoryId && row.rateKey);

const categoryMap = (rows: CategoryRow[]) =>
  new Map(complete(rows).map((row) => [row.categoryId, row.rateKey]));

function isDirty(
  rates: RateRow[],
  categories: CategoryRow[],
  savedRates: TaxRate[],
  savedCategories: CategoryTaxRate[],
): boolean {
  const byId = new Map(savedRates.map((r) => [r.id, r]));
  if (rates.length !== savedRates.length) return true;
  if (rates.some((row) => !row.id || rateChanged(row, byId.get(row.id))))
    return true;
  const drafted = categoryMap(categories);
  if (drafted.size !== savedCategories.length) return true;
  return savedCategories.some(
    (c) => drafted.get(c.category_id) !== c.tax_rate_id,
  );
}

/** Deletes, edits and adds the rates; answers each row's key → saved id. */
async function saveRates(
  rows: RateRow[],
  saved: TaxRate[],
): Promise<Map<string, string>> {
  const kept = new Set(rows.map((row) => row.id).filter(Boolean));
  for (const rate of saved) {
    if (!kept.has(rate.id)) await taxRatesApi.delete(rate.id);
  }
  const ids = new Map<string, string>();
  const byId = new Map(saved.map((r) => [r.id, r]));
  for (const row of rows) {
    const body = { name: row.name.trim(), rate: row.rate };
    if (row.id) {
      if (rateChanged(row, byId.get(row.id)))
        await taxRatesApi.update(row.id, body);
      ids.set(row.key, row.id);
    } else {
      ids.set(
        row.key,
        (await taxRatesApi.create({ ...body, is_default: false })).id,
      );
    }
  }
  return ids;
}

async function saveCategories(
  rows: CategoryRow[],
  saved: CategoryTaxRate[],
  ids: Map<string, string>,
): Promise<void> {
  const drafted = categoryMap(rows);
  for (const c of saved) {
    // A category whose rate was deleted lost its row with it.
    if (!drafted.has(c.category_id) && ids.has(c.tax_rate_id))
      await taxRatesApi.nameCategoryRate(c.category_id, null);
  }
  const before = new Map(saved.map((c) => [c.category_id, c.tax_rate_id]));
  for (const [categoryId, rateKey] of drafted) {
    const rateId = ids.get(rateKey);
    if (rateId && before.get(categoryId) !== rateId)
      await taxRatesApi.nameCategoryRate(categoryId, rateId);
  }
}

/**
 * The tax-rate table and the categories naming a rate, as one draft the
 * page's Save writes.
 *
 * Rates are written before the categories, because a category may name a
 * rate added in the same edit: the row's key stands for it until the server
 * gives it an id.
 */
export function useTaxRatesDraft() {
  const queryClient = useQueryClient();
  const ratesQuery = useTaxRates();
  const categoriesQuery = useCategoryTaxRates();
  const [rates, setRates] = useState<RateRow[] | null>(null);
  const [categories, setCategories] = useState<CategoryRow[] | null>(null);
  const savedRates = ratesQuery.data;
  const savedCategories = categoriesQuery.data;

  useEffect(() => {
    if (savedRates && rates === null) setRates(toRateRows(savedRates));
  }, [savedRates, rates]);
  useEffect(() => {
    if (savedCategories && categories === null)
      setCategories(toCategoryRows(savedCategories));
  }, [savedCategories, categories]);

  const ready =
    rates !== null &&
    categories !== null &&
    savedRates !== undefined &&
    savedCategories !== undefined;
  const dirty =
    ready && isDirty(rates, categories, savedRates, savedCategories);

  usePageSavePart("taxRates", dirty, async () => {
    if (!ready) return;
    try {
      const ids = await saveRates(rates, savedRates);
      await saveCategories(categories, savedCategories, ids);
    } finally {
      // Whatever part was written is what the server holds now; the form
      // is read again from it rather than kept as the draft that half-failed.
      await queryClient.invalidateQueries({
        queryKey: queryKeys.documents.taxRates,
      });
      setRates(null);
      setCategories(null);
    }
  });

  return {
    rates,
    categories,
    setRates,
    setCategories,
    isError: ratesQuery.isError || categoriesQuery.isError,
    refetch: () => {
      void ratesQuery.refetch();
      void categoriesQuery.refetch();
    },
  };
}
