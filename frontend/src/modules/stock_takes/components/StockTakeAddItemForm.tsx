import { useTranslation } from "react-i18next";
import { useScopedCategories } from "@/modules/shared/hooks/useCategories";
import { useFlatUoms } from "@/modules/shared/hooks/useUoms";
import { extractApiError } from "@/lib/errors";
import { categoryLabel, unitLabel } from "@/lib/i18nHelpers";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { NativeSelect } from "@/components/ui/NativeSelect";

interface Props {
  name: string;
  barcode: string;
  quantity: number;
  categoryId: string;
  uomId: string;
  isPending: boolean;
  error: unknown;
  onNameChange: (value: string) => void;
  onBarcodeChange: (value: string) => void;
  onQuantityChange: (value: number) => void;
  onCategoryIdChange: (value: string) => void;
  onUomIdChange: (value: string) => void;
  onSubmit: () => void;
}

/**
 * Short form that creates a product in the counted
 * location and registers it as a surplus. Category and unit of measure
 * are chosen here so the ad-hoc product is correctly described from
 * the start.
 */
export default function StockTakeAddItemForm({
  name,
  barcode,
  quantity,
  categoryId,
  uomId,
  isPending,
  error,
  onNameChange,
  onBarcodeChange,
  onQuantityChange,
  onCategoryIdChange,
  onUomIdChange,
  onSubmit,
}: Props) {
  const { t } = useTranslation(["stock_takes", "common"]);
  // The picker offers categories on a general screen, so it follows the same
  // module-data policy as the lists. `keepId` keeps a chosen category
  // selectable if the policy later hides it.
  const { scoped: categories } = useScopedCategories(categoryId);
  const { data: uoms } = useFlatUoms();

  return (
    <div className="mt-3 p-3 bg-surface rounded-lg space-y-2">
      <Input
        type="text"
        value={name}
        onChange={(e) => onNameChange(e.target.value)}
        placeholder={t("addNewItemForm.nameLabel")}
        aria-label={t("addNewItemForm.nameLabel")}
      />
      <div className="flex gap-2">
        <Input
          type="text"
          value={barcode}
          onChange={(e) => onBarcodeChange(e.target.value)}
          placeholder={t("addNewItemForm.barcodeLabel")}
          aria-label={t("addNewItemForm.barcodeLabel")}
        />
        <Input
          wrapperClassName="w-20"
          type="number"
          value={quantity}
          onChange={(e) => onQuantityChange(parseInt(e.target.value, 10) || 1)}
          min="1"
          aria-label={t("addNewItemForm.quantityLabel")}
        />
      </div>
      <div className="flex gap-2">
        <NativeSelect
          value={categoryId}
          onChange={(e) => onCategoryIdChange(e.target.value)}
          aria-label={t("addNewItemForm.categoryLabel")}
        >
          <option value="">{t("addNewItemForm.categoryPlaceholder")}</option>
          {categories?.map((category) => (
            <option key={category.id} value={category.id}>
              {categoryLabel(t, category.code, category.name)}
            </option>
          ))}
        </NativeSelect>
        <NativeSelect
          value={uomId}
          onChange={(e) => onUomIdChange(e.target.value)}
          aria-label={t("addNewItemForm.uomLabel")}
        >
          <option value="">{t("addNewItemForm.uomPlaceholder")}</option>
          {uoms?.map((uom) => (
            <option key={uom.id} value={uom.id}>
              {unitLabel(t, uom.symbol) || uom.name}
            </option>
          ))}
        </NativeSelect>
      </div>
      {Boolean(error) && !isPending && (
        <p className="text-sm text-red-600">
          {extractApiError(error, t("errors.addItemFailed"))}
        </p>
      )}
      <Button
        size="content"
        type="button"
        onClick={onSubmit}
        disabled={isPending || !name.trim()}
        className="py-2"
      >
        {isPending ? t("common:actions.saving") : t("common:actions.add")}
      </Button>
    </div>
  );
}
