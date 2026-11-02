import { useModuleQuery } from "@/hooks/queries/useModuleQuery";
import { queryKeys } from "@/hooks/queries/keys";
import { useAppMutation } from "@/lib/api/mutationFactory";
import {
  taxRatesApi,
  type CategoryTaxRate,
  type CountryRates,
  type ProductTaxRate,
  type TaxRate,
} from "@/modules/warehouse/api/taxRates";

/** The organization's tax rates, oldest first. */
export function useTaxRates() {
  return useModuleQuery<TaxRate[]>("warehouse", {
    queryKey: queryKeys.documents.taxRates,
    queryFn: () => taxRatesApi.list(),
  });
}

/** The rates the organization's country offers to start from. */
export function useCountryTaxRates() {
  return useModuleQuery<CountryRates>("warehouse", {
    queryKey: queryKeys.documents.taxRatesCountry,
    queryFn: () => taxRatesApi.countryRates(),
    staleTime: 60 * 60 * 1000,
  });
}

/** Every category that names a rate. */
export function useCategoryTaxRates() {
  return useModuleQuery<CategoryTaxRate[]>("warehouse", {
    queryKey: queryKeys.documents.taxRatesCategories,
    queryFn: () => taxRatesApi.listCategoryRates(),
  });
}

/** The rate a product names, and the one its category would give it. */
export function useProductTaxRate(templateId: string | null | undefined) {
  return useModuleQuery<ProductTaxRate>("warehouse", {
    queryKey: queryKeys.documents.taxRateOfProduct(templateId ?? ""),
    queryFn: () => taxRatesApi.productRate(templateId as string),
    extraEnabled: Boolean(templateId),
  });
}

export function useNameProductTaxRate(templateId: string) {
  return useAppMutation(
    (taxRateId: string | null) =>
      taxRatesApi.nameProductRate(templateId, taxRateId),
    (qc, data) => {
      qc.setQueryData(queryKeys.documents.taxRateOfProduct(templateId), data);
    },
  );
}
