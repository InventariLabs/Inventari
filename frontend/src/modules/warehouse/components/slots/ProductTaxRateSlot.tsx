import { useId } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { NativeSelect } from "@/components/ui/NativeSelect";
import { useCanManage } from "@/hooks/useCanWrite";
import {
  useNameProductTaxRate,
  useProductTaxRate,
  useTaxRates,
} from "@/modules/warehouse/hooks/useTaxRates";
import type { Item } from "@/types";
import { extractApiError } from "@/lib/errors";

/**
 * The tax rate a product's document and order lines take, on its edit form.
 *
 * A product names one of the organization's rates, or leaves it to its
 * category and then to the document default. The choice is the warehouse
 * module's own record, saved the moment it is picked — the form's Save
 * writes the product's Core fields only. Nothing renders while the
 * organization keeps no rates to pick from.
 */
export default function ProductTaxRateSlot({ data }: { data: { item: Item } }) {
  const { t } = useTranslation("warehouse");
  const id = useId();
  const canManage = useCanManage("warehouse");
  const templateId = data.item.template_id ?? "";
  const { data: rates } = useTaxRates();
  // Asked only once there is a rate to pick: most organizations keep none.
  const { data: named } = useProductTaxRate(rates?.length ? templateId : null);
  const save = useNameProductTaxRate(templateId);

  if (!templateId || !rates?.length || !named) return null;

  const byId = new Map(rates.map((r) => [r.id, r.name]));
  const inherited = named.category_tax_rate_id
    ? t("taxRates.product.fromCategory", {
        rate: byId.get(named.category_tax_rate_id) ?? "—",
      })
    : t("taxRates.product.fromDefault");

  const pick = async (value: string) => {
    try {
      await save.mutateAsync(value || null);
      toast.success(t("taxRates.product.saved"));
    } catch (error) {
      toast.error(extractApiError(error, t("taxRates.product.saveFailed")));
    }
  };

  return (
    <NativeSelect
      id={id}
      label={t("taxRates.product.label")}
      description={t("taxRates.product.hint")}
      value={named.tax_rate_id ?? ""}
      disabled={!canManage || save.isPending}
      onChange={(e) => void pick(e.target.value)}
    >
      <option value="">{inherited}</option>
      {rates.map((r) => (
        <option key={r.id} value={r.id}>
          {r.name}
        </option>
      ))}
    </NativeSelect>
  );
}
