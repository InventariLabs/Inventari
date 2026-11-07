import { useState } from "react";
import { AlertTriangle, X, Loader2, Save } from "lucide-react";
import { useTranslation } from "react-i18next";
import { extractApiError } from "@/lib/errors";
import type { ItemUpdate } from "@/types";
import { toast } from "sonner";
import { useOrganizationCurrency } from "@/hooks/useOrganizationCurrency";
import { useShowInventoryValue } from "@/modules/shared/hooks/useShowInventoryValue";
import { useScopedCategories } from "@/modules/shared/hooks/useCategories";
import { categoryLabel } from "@/lib/i18nHelpers";
import { useBulkUpdateItems } from "@/modules/inventory/hooks/useItemMutations";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { DateInput } from "@/components/ui/DateInput";
import { NativeSelect } from "@/components/ui/NativeSelect";
import { LocationCombobox } from "@/module-sdk";
import { Checkbox } from "@/components/ui/Checkbox";
import { Sheet, SheetActions, SheetFooter } from "@/components/ui/Sheet";

type BulkFormData = Omit<ItemUpdate, "purchase_price"> & {
  location_id?: string;
  purchase_price?: number | string | null;
};

interface Props {
  itemIds: string[];
  onClose: () => void;
  onSuccess: () => void;
}

/**
 * The one sentence that says a mistake reaches N records. Its glyph travels
 * as an icon, not baked into the catalogue string: a translation that
 * carries an emoji cannot be read aloud, and the adjacent text already says
 * "warning".
 */
function BulkEditWarning({ count }: { count: number }) {
  const { t } = useTranslation("items");
  return (
    <div className="p-4 bg-amber-50 rounded-2xl border border-amber-100 text-amber-800 text-sm leading-relaxed">
      <p className="flex items-start gap-2">
        <AlertTriangle
          size={16}
          aria-hidden="true"
          className="shrink-0 mt-0.5 text-amber-700"
        />
        <span>
          <strong className="font-semibold text-amber-900">
            {t("bulkEdit.warning")}
          </strong>{" "}
          {t("bulkEdit.warningText", { count })}
        </span>
      </p>
    </div>
  );
}

/**
 * The price row. The price feeds the stock value, so where the organization
 * does not show that value the item form drops the field and the bulk edit
 * drops this row: nothing on screen would read the figure back.
 */
function BulkPriceField({
  enabled,
  onToggle,
  value,
  onChange,
}: {
  enabled: boolean;
  onToggle: () => void;
  value: BulkFormData["purchase_price"];
  onChange: (value: string) => void;
}) {
  const { t } = useTranslation("items");
  const currency = useOrganizationCurrency();
  const showInventoryValue = useShowInventoryValue();
  if (!showInventoryValue) return null;
  return (
    <div className="space-y-2">
      <Checkbox
        checked={enabled}
        onChange={onToggle}
        className="w-5 h-5 rounded-lg border border-border text-primary-600 focus:ring-primary-500 transition-all"
        label={
          <span
            className={`font-medium text-xs uppercase tracking-[0.1em] ${enabled ? "text-on" : "text-on-muted"}`}
          >
            {t("bulkEdit.price")} ({currency})
          </span>
        }
      />
      {enabled && (
        <Input
          type="text"
          inputMode="decimal"
          aria-label={t("bulkEdit.price")}
          value={value === undefined ? "" : (value ?? "")}
          onChange={(e) => onChange(e.target.value)}
          placeholder="0.00"
        />
      )}
    </div>
  );
}

export default function BulkEditModal({ itemIds, onClose, onSuccess }: Props) {
  const { t } = useTranslation(["items", "common", "categories"]);

  // Track which fields should be updated
  const [enabledFields, setEnabledFields] = useState<Record<string, boolean>>({
    location_id: false,
    category_id: false,
    purchase_price: false,
    brand: false,
    unit: false,
    expiry_date: false,
  });

  const [formData, setFormData] = useState<BulkFormData>({
    location_id: "",
    category_id: "",
    purchase_price: undefined,
    brand: "",
    expiry_date: "",
    unit_confirmed_over_template: false,
  });

  // The location a bulk change offers is a stock flow's: what may hold stock,
  // never a place a module owns — a bulk move sends records there, and the
  // equipment module runs a batch move over its own locations itself. The
  // category beside it keeps the product list's scope: a bulk change to a
  // category the list keeps out of view would move records where the reader
  // cannot see.
  const { scoped: categories } = useScopedCategories();
  const bulkMutation = useBulkUpdateItems();

  /**
   * The warning the category select owes the reader, when the category it
   * holds is one a module owns. Resolved here rather than beside the select:
   * the module's name answers to the translation catalogues, and a t() call
   * nested in another t()'s options reads like nonsense to everyone —
   * humans included.
   */
  const pickedModuleWarning = (() => {
    const picked = categories?.find(
      (c) => c.id === (formData.category_id || ""),
    );
    if (!picked?.is_module_owned) return null;
    const owner = picked.module_name ?? picked.context_tag ?? "";
    return {
      categoryName: categoryLabel(t, picked.code, picked.name),
      moduleName: owner
        ? t(`modules.${owner}.name`, { ns: "modules", defaultValue: owner })
        : owner,
    };
  })();

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();

    const updateData: Record<string, unknown> = {};
    let hasFields = false;

    Object.keys(enabledFields).forEach((key) => {
      if (enabledFields[key]) {
        let val = formData[key as keyof BulkFormData];

        // Handle numeric conversion
        if (key === "purchase_price" && typeof val === "string") {
          val = parseFloat(val.replace(",", "."));
          if (isNaN(val)) val = undefined;
        }

        if (val !== undefined && val !== "") {
          updateData[key] = val;
          hasFields = true;
        }
      }
    });

    if (!hasFields) {
      toast.error(t("bulkEdit.errorNoFields"));
      return;
    }

    bulkMutation.mutate(
      {
        item_ids: itemIds,
        // The contract requires the confirmation flag; a bulk edit changes no
        // unit, which is the flag's "no" — the same answer the server used to
        // default to when the payload omitted it.
        update_data: {
          ...updateData,
          unit_confirmed_over_template: false,
        } as ItemUpdate,
      },
      {
        onSuccess: (data) => {
          toast.success(
            t("bulkEdit.successUpdated", {
              count: (data as { updated: number }).updated,
            }),
          );
          onSuccess();
        },
        onError: (error: unknown) => {
          toast.error(extractApiError(error, t("bulkEdit.errorUpdate")));
        },
      },
    );
  };

  const anyFieldTicked = Object.values(enabledFields).some(Boolean);

  const toggleField = (field: string) => {
    setEnabledFields((prev) => ({ ...prev, [field]: !prev[field] }));
  };

  return (
    <Sheet
      open
      onClose={onClose}
      zIndex="modal-nested"
      aria-label={t("bulkEdit.title", { count: itemIds.length })}
    >
      {/* Header */}
      <div className="p-6 border-b flex items-center justify-between">
        <div>
          <h3 className="text-xl font-semibold text-on">
            {t("bulkEdit.title", { count: itemIds.length })}
          </h3>
          <p className="text-sm text-on-secondary">{t("bulkEdit.subtitle")}</p>
        </div>
        <Button
          variant="ghost"
          size="icon"
          onClick={onClose}
          aria-label={t("common:a11y.close")}
        >
          <X size={24} />
        </Button>
      </div>

      <form
        onSubmit={handleSubmit}
        className="p-6 overflow-y-auto space-y-6 custom-scrollbar"
      >
        {/* Storage Field */}
        <div className="space-y-2">
          <Checkbox
            checked={enabledFields.location_id}
            onChange={() => toggleField("location_id")}
            className="w-5 h-5 rounded-lg border border-border text-primary-600 focus:ring-primary-500 transition-all"
            label={
              <span
                className={`font-medium text-xs uppercase tracking-[0.1em] ${enabledFields.location_id ? "text-on" : "text-on-muted"}`}
              >
                {t("bulkEdit.location")}
              </span>
            }
          />
          {enabledFields.location_id && (
            <LocationCombobox
              aria-label={t("bulkEdit.location")}
              title={t("bulkEdit.location")}
              scope={{ purpose: "stock" }}
              value={formData.location_id || ""}
              onChange={(id) => setFormData({ ...formData, location_id: id })}
              placeholder={t("bulkEdit.selectLocation")}
              searchPlaceholder={t("common:actions.search")}
              emptyMessage={t("common:noResults")}
            />
          )}
        </div>

        {/* Category Field */}
        <div className="space-y-2">
          <Checkbox
            checked={enabledFields.category_id}
            onChange={() => toggleField("category_id")}
            className="w-5 h-5 rounded-lg border border-border text-primary-600 focus:ring-primary-500 transition-all"
            label={
              <span
                className={`font-medium text-xs uppercase tracking-[0.1em] ${enabledFields.category_id ? "text-on" : "text-on-muted"}`}
              >
                {t("bulkEdit.category")}
              </span>
            }
          />
          {enabledFields.category_id && (
            <NativeSelect
              aria-label={t("bulkEdit.category")}
              value={formData.category_id || ""}
              onChange={(e) =>
                setFormData({ ...formData, category_id: e.target.value })
              }
            >
              <option value="">{t("bulkEdit.selectCategory")}</option>
              {categories?.map((c) => (
                <option key={c.id} value={c.id}>
                  {categoryLabel(t, c.code, c.name)}
                </option>
              ))}
            </NativeSelect>
          )}
          {enabledFields.category_id && pickedModuleWarning && (
            <p
              className="rounded-lg bg-amber-50 p-2.5 text-xs leading-relaxed text-on-warning"
              data-testid="category-module-warning"
            >
              {t("items:categoryModuleWarning", {
                category: pickedModuleWarning.categoryName,
                module: pickedModuleWarning.moduleName,
              })}
            </p>
          )}
        </div>

        <BulkPriceField
          enabled={enabledFields.purchase_price}
          onToggle={() => toggleField("purchase_price")}
          value={formData.purchase_price}
          onChange={(value) =>
            setFormData({ ...formData, purchase_price: value })
          }
        />

        {/* Brand Field */}
        <div className="space-y-2">
          <Checkbox
            checked={enabledFields.brand}
            onChange={() => toggleField("brand")}
            className="w-5 h-5 rounded-lg border border-border text-primary-600 focus:ring-primary-500 transition-all"
            label={
              <span
                className={`font-medium text-xs uppercase tracking-[0.1em] ${enabledFields.brand ? "text-on" : "text-on-muted"}`}
              >
                {t("bulkEdit.brand")}
              </span>
            }
          />
          {enabledFields.brand && (
            <Input
              type="text"
              aria-label={t("bulkEdit.brand")}
              value={formData.brand || ""}
              onChange={(e) =>
                setFormData({ ...formData, brand: e.target.value })
              }
              placeholder={t("bulkEdit.brandPlaceholder")}
            />
          )}
        </div>

        {/* Expiry Date Field */}
        <div className="space-y-2">
          <Checkbox
            checked={enabledFields.expiry_date}
            onChange={() => toggleField("expiry_date")}
            className="w-5 h-5 rounded-lg border border-border text-primary-600 focus:ring-primary-500 transition-all"
            label={
              <span
                className={`font-medium text-xs uppercase tracking-[0.1em] ${enabledFields.expiry_date ? "text-on" : "text-on-muted"}`}
              >
                {t("bulkEdit.expiryDate")}
              </span>
            }
          />
          {enabledFields.expiry_date && (
            <DateInput
              aria-label={t("bulkEdit.expiryDate")}
              value={formData.expiry_date || ""}
              onChange={(value) =>
                setFormData({ ...formData, expiry_date: value })
              }
              presets={["plus1Week", "plus1Month", "plus6Months"]}
            />
          )}
        </div>

        {/* The one sentence that says a mistake reaches N records — a
            warning the reader must be able to read. */}
        <BulkEditWarning count={itemIds.length} />
      </form>

      {/* Footer */}
      <SheetFooter>
        <SheetActions>
          <Button variant="outline" onClick={onClose}>
            {t("bulkEdit.cancel")}
          </Button>
          {/* Waits for a ticked field: the subtitle above says to pick one,
              and a press with none was only answered by a toast saying it
              again. A field ticked and left empty still answers on press. */}
          <Button
            onClick={handleSubmit}
            disabled={bulkMutation.isPending || !anyFieldTicked}
          >
            {bulkMutation.isPending ? (
              <Loader2 size={20} className="animate-spin" />
            ) : (
              <Save size={20} />
            )}
            {t("bulkEdit.apply")}
          </Button>
        </SheetActions>
      </SheetFooter>
    </Sheet>
  );
}
