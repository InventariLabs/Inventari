import { forwardRef } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import { Settings2 } from "lucide-react";
import { NativeSelect } from "@/components/ui/NativeSelect";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { useConfirm } from "@/hooks/useConfirm";
import { getCategoryLabel } from "@/modules/equipment/components/assetUtils";
import type { CategoryDTO } from "@/types";

const fieldLabel =
  "block text-xs font-medium uppercase tracking-wide text-on-secondary ml-1";

interface EquipmentCategoryFieldProps {
  value: string;
  categories: CategoryDTO[];
  /** Values already typed into the category-declared fields, if any. */
  hasDynamicData: boolean;
  required?: boolean;
  error?: string;
  onChange: (categoryId: string) => void;
}

/**
 * The category picker, with the confirmation that changing it clears the
 * category-declared fields. Lives on its own because it owns that dialog —
 * and because it is what decides whether the asset list will find the record.
 */
export const EquipmentCategoryField = forwardRef<
  HTMLSelectElement,
  EquipmentCategoryFieldProps
>(function EquipmentCategoryField(
  { value, categories, hasDynamicData, required = false, error, onChange },
  ref,
) {
  const { t } = useTranslation("equipment");
  // Changing the category silently wipes dynamic-field values. Guard
  // the swap with a confirm when the user has already entered data.
  const { confirm, confirmDialogProps } = useConfirm();

  const handleChange = async (nextCategoryId: string) => {
    if (nextCategoryId === value) return;
    if (!hasDynamicData) {
      onChange(nextCategoryId);
      return;
    }
    const ok = await confirm({
      title: t("form.confirmCategoryChangeTitle", "Change category?"),
      message: t(
        "form.confirmCategoryChangeMessage",
        "Switching category will clear the values you have already entered in the category-specific fields.",
      ),
      variant: "danger",
      confirmLabel: t("form.confirmCategoryChange", "Change"),
    });
    if (ok) onChange(nextCategoryId);
  };

  return (
    <div className="space-y-1.5">
      <div className="flex items-center justify-between">
        <label className={fieldLabel} htmlFor="equipment-category">
          {t("form.fields.category", "Category")}
          {required && <span className="text-red-500 ml-1">*</span>}
        </label>
        <Link
          to="/equipment/categories"
          className="flex items-center gap-1 text-xs text-primary-500 hover:text-primary-600 transition-colors"
        >
          <Settings2 size={12} />
          {t("form.manageCategories", "Manage")}
        </Link>
      </div>
      <NativeSelect
        id="equipment-category"
        ref={ref}
        value={value}
        onChange={(e) => handleChange(e.target.value)}
        required={required}
        aria-required={required || undefined}
        aria-invalid={Boolean(error)}
      >
        <option value="">
          {t("form.placeholders.category", "Select category…")}
        </option>
        {categories.map((c: CategoryDTO) => (
          <option key={c.id} value={c.id}>
            {getCategoryLabel(t, { code: c.code, name: c.name })}
          </option>
        ))}
      </NativeSelect>
      {error && (
        <p role="alert" className="text-xs text-red-500 ml-1">
          {error}
        </p>
      )}
      <ConfirmDialog {...confirmDialogProps} />
    </div>
  );
});
