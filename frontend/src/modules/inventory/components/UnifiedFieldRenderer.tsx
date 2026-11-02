import { useId } from "react";
import { FieldDefinition, CategoryDTO, Uom } from "@/types";
import { makeTDynamic, unitLabel } from "@/lib/i18nHelpers";
import { useTranslation } from "react-i18next";
import { useUoms } from "@/modules/shared/hooks/useUoms";
import { UomSelect } from "@/modules/shared/components/UomSelect";
import { Input } from "@/components/ui/Input";
import { FIELD_LABEL_CLASS, RequiredStar } from "@/components/ui/fieldLabel";
import { cn } from "@/lib/utils";
import { getPlaceholder, getLabel } from "./FieldRenderers/helpers";
import type { TemplateUnitPrompt } from "@/modules/inventory/hooks/useItemForm";
import { CategoryField } from "./FieldRenderers/CategoryField";
import { UnitField } from "./FieldRenderers/UnitField";
import { WeightField } from "./FieldRenderers/WeightField";
import { TextareaField } from "./FieldRenderers/TextareaField";
import { DateField } from "./FieldRenderers/DateField";
import { FileField } from "./FieldRenderers/FileField";
import { DefaultInputField } from "./FieldRenderers/DefaultInputField";
import { BarcodeField } from "./FieldRenderers/BarcodeField";
import { MoneyField } from "./FieldRenderers/MoneyFieldView";
import { MultiSelectField } from "./FieldRenderers/MultiSelectField";
import { SelectField } from "./FieldRenderers/SelectField";
import { BooleanField } from "./FieldRenderers/BooleanField";

interface UnifiedFieldRendererProps {
  fieldDefinitions: FieldDefinition[];
  formData: Record<string, unknown>;
  onChange: (key: string, value: unknown, isMetadata?: boolean) => void;
  onUomChange?: (uomId: string, uom: Uom) => void;
  onFileSelect?: (fieldKey: string, file: File) => void;
  errors?: Record<string, string>;
  className?: string;
  categories?: CategoryDTO[];
  onAddCategory?: () => void;
  onConfigureCategoryFields?: (categoryId: string) => void;
  /**
   * The unit the matched product template keeps, when the catalogue knows the
   * product being typed. Shown beside the picker as the unit the record will
   * land with, so "a quantity of what" is answered before the save.
   */
  templateUnit?: TemplateUnitPrompt | null;
}

/**
 * Whether the control says its own error, linked to itself. The wrapper
 * prints the message for every other renderer; printing it for these too
 * showed an invalid field's "Required" twice. Mirrors the branches of
 * `renderField` below, in its order.
 */
function controlSaysItsError(field: FieldDefinition): boolean {
  if (field.key === "category_id" || field.key === "weight") return false;
  if (field.key === "unit") return true;
  if (
    ["textarea", "date", "file", "money", "multi-select", "boolean"].includes(
      field.type,
    )
  ) {
    return false;
  }
  return field.type === "select" || field.key === "barcode";
}

export default function UnifiedFieldRenderer({
  fieldDefinitions,
  formData,
  onChange,
  onUomChange,
  onFileSelect,
  errors = {},
  className = "",
  categories = [],
  onAddCategory,
  onConfigureCategoryFields,
  templateUnit = null,
}: UnifiedFieldRendererProps) {
  const { t } = useTranslation(["items", "common", "categories"]);
  const tDyn = makeTDynamic(t);
  const { data: uomCategories } = useUoms();

  // Type-safe accessors for known formData fields
  const fdUomId = formData.uom_id as string | undefined;

  // The unit the price is *per*, when one has been picked. The field sits
  // directly under "quantity 10" and a unit button, so "45" naturally reads as
  // what the invoice says — the price of the ten kilos. It is the rate, and
  // everything downstream treats it as one: a valuation layer is opened at
  // this unit cost, AVCO comes off those layers, and a production cost is
  // rate × quantity. Ten kilos of wax at 45 became 450 per candle.
  const priceUnit = uomCategories
    ?.flatMap((category) => category.uoms ?? [])
    .find((uom) => uom.id === fdUomId);
  const fdQuantity = formData.quantity as string | undefined;
  const fdMetadata = formData.metadata as Record<string, unknown> | undefined;

  // Each field's label needs an id to point at. Field keys are unique within
  // one set of definitions, but the same renderer appears several times on a
  // page (identity, storage, …) and twice over when a modal opens on top of a
  // form — hence the per-instance prefix.
  const idPrefix = useId();
  const fieldId = (field: FieldDefinition) => `${idPrefix}${field.key}`;

  // Unit renders a picker with no single focusable field, and multi-select is
  // a group of checkboxes — in those two `htmlFor` would point at nothing, so
  // the label stays plain text. Category takes the id on its combobox trigger
  // (a `<button>` is labelable), which is what names the control.
  const takesFieldId = (field: FieldDefinition) =>
    field.key !== "unit" && field.type !== "multi-select";

  if (!fieldDefinitions || fieldDefinitions.length === 0) return null;

  // Filter only visible fields
  const visibleFields = fieldDefinitions.filter((f) => f.visible);

  if (visibleFields.length === 0) return null;

  // Custom logic to group quantity and unit
  const hasQuantity = visibleFields.some((f) => f.key === "quantity");
  const hasUnit = visibleFields.some((f) => f.key === "unit");
  const shouldGroupQuantityUnit = hasQuantity && hasUnit;

  const renderField = (field: FieldDefinition, id: string) => {
    const isMetadata = field.is_custom !== false;
    let value: unknown;
    if (isMetadata) {
      value = fdMetadata?.[field.key];
    } else {
      value = formData[field.key];
    }
    if (value === undefined || value === null) value = "";

    const handleChange = (val: unknown) => {
      onChange(field.key, val, isMetadata);
    };

    const commonClasses = `w-full px-4 py-2.5 bg-surface-card border rounded-lg focus:border-primary-500 focus:ring-2 focus:ring-primary-500/20 transition-all outline-none text-sm font-medium text-on ${
      errors[field.key] ? "border-red-300 bg-red-50" : "border-border"
    }`;

    // Special Handling for specific field types
    if (field.key === "category_id") {
      return (
        <CategoryField
          id={id}
          value={String(value)}
          categories={categories}
          onChange={handleChange}
          onAddCategory={onAddCategory}
          onConfigureCategoryFields={onConfigureCategoryFields}
        />
      );
    }

    if (field.key === "weight") {
      return (
        <WeightField
          id={id}
          field={field}
          value={value}
          weightUomId={formData.weight_uom_id as string | undefined}
          quantity={fdQuantity}
          error={errors[field.key]}
          onChange={handleChange}
          onUomChange={(uomId) => onChange("weight_uom_id", uomId, false)}
        />
      );
    }

    if (field.key === "unit") {
      return (
        <UnitField
          uomId={fdUomId}
          error={errors[field.key]}
          onChange={(uomId, uom) => {
            onChange("uom_id", uomId, false);
            if (onUomChange) onUomChange(uomId, uom);
          }}
        />
      );
    }

    if (field.type === "textarea") {
      return (
        <TextareaField
          id={id}
          field={field}
          value={value}
          commonClasses={commonClasses}
          error={errors[field.key]}
          onChange={handleChange}
        />
      );
    }

    if (field.type === "date") {
      return (
        <DateField
          id={id}
          field={field}
          value={value}
          error={errors[field.key]}
          onChange={handleChange}
        />
      );
    }

    if (field.type === "file") {
      return (
        <FileField
          id={id}
          field={field}
          value={value}
          commonClasses={commonClasses}
          onFileSelect={onFileSelect}
          onChange={handleChange}
        />
      );
    }

    if (field.type === "money") {
      return (
        <MoneyField
          id={id}
          field={field}
          value={value}
          commonClasses={commonClasses}
          error={errors[field.key]}
          onChange={handleChange}
        />
      );
    }

    if (field.type === "multi-select") {
      return (
        <MultiSelectField
          field={field}
          value={value}
          error={errors[field.key]}
          onChange={handleChange}
        />
      );
    }

    if (field.type === "select") {
      return (
        <SelectField
          id={id}
          field={field}
          value={value}
          error={errors[field.key]}
          onChange={handleChange}
          tDyn={tDyn}
        />
      );
    }

    if (field.type === "boolean") {
      return (
        <BooleanField
          id={id}
          field={field}
          value={value}
          error={errors[field.key]}
          onChange={handleChange}
        />
      );
    }

    if (field.key === "barcode") {
      return (
        <BarcodeField
          id={id}
          field={field}
          value={value}
          error={errors[field.key]}
          onChange={handleChange}
        />
      );
    }

    // Default: text, number, etc.
    return (
      <DefaultInputField
        id={id}
        field={field}
        value={value}
        quantity={fdQuantity}
        uomId={fdUomId}
        uomCategories={uomCategories}
        error={errors[field.key]}
        onChange={handleChange}
      />
    );
  };

  return (
    <div
      className={`grid grid-cols-1 md:grid-cols-2 gap-x-6 gap-y-5 ${className}`}
    >
      {visibleFields.map((field) => {
        // Weight visibility follows the unit's category and is decided in
        // computeFieldDefinitions — a second rule here is how the two used
        // to disagree.

        // If we are grouping quantity and unit, and this is 'unit', skip it
        if (shouldGroupQuantityUnit && field.key === "unit") return null;

        // If this is 'quantity' and we are grouping, render both
        if (shouldGroupQuantityUnit && field.key === "quantity") {
          return (
            <div
              key="grouped-quantity-unit"
              data-field-key="quantity"
              className="md:col-span-1 space-y-1.5"
            >
              <label htmlFor={fieldId(field)} className={FIELD_LABEL_CLASS}>
                {getLabel(field, tDyn)}
              </label>
              <div className="flex items-stretch gap-2">
                <div className="flex-1 relative">
                  <Input
                    id={fieldId(field)}
                    type="number"
                    inputMode="decimal"
                    step="any"
                    // `|| ""` blanked a quantity of 0: the field then looked
                    // unset, and an item genuinely at zero could be saved back
                    // as whatever the reader typed over the emptiness.
                    value={fdQuantity ?? ""}
                    onChange={(e) => {
                      let val: string | null = e.target.value;
                      if (val === "") val = null;
                      else val = val.replace(",", ".");
                      onChange("quantity", val, false);
                    }}
                    placeholder={getPlaceholder(field, undefined, tDyn)}
                    className={
                      errors.quantity ? "border-red-300 bg-red-50" : ""
                    }
                  />
                </div>
                <div className="w-28 self-stretch">
                  {/* UomSelect for grouped unit picker */}
                  <UomSelect
                    compact
                    value={fdUomId || null}
                    onChange={(uomId, uom) => {
                      onChange("uom_id", uomId, false);
                      if (onUomChange) onUomChange(uomId, uom);
                    }}
                  />
                </div>
              </div>
              {/* Where the record's unit comes from, said before the save.
                  The catalogue counts this product in one unit, and the save
                  lands there unless the reader deliberately picks another —
                  a picker that says nothing leaves them guessing which. */}
              {templateUnit && (
                <p
                  className="text-xs text-on-muted ml-1"
                  data-testid="items-template-unit-hint"
                >
                  {t("items:form.templateUnitHint", {
                    product: templateUnit.productName,
                    unit: unitLabel(t, templateUnit.uomSymbol),
                  })}
                </p>
              )}
              {errors.quantity && (
                <p className="text-xs text-red-600 font-medium ml-1">
                  {errors.quantity}
                </p>
              )}
            </div>
          );
        }

        return (
          <div
            key={field.key}
            data-field-key={field.key}
            className={cn(
              "space-y-1.5",
              (field.type === "textarea" || field.key === "name") &&
                "md:col-span-2",
            )}
          >
            <label
              htmlFor={takesFieldId(field) ? fieldId(field) : undefined}
              className={FIELD_LABEL_CLASS}
            >
              {getLabel(field, tDyn)}
              {field.required && <RequiredStar />}
            </label>

            {renderField(field, fieldId(field))}

            {field.key === "purchase_price" && priceUnit && (
              <p className="text-xs text-on-muted ml-1">
                {t("items:fields.purchasePriceUnitHint", {
                  unit: unitLabel(t, priceUnit.symbol) || priceUnit.name,
                })}
              </p>
            )}

            {errors[field.key] && !controlSaysItsError(field) && (
              <p className="text-xs text-red-600 font-medium ml-1">
                {errors[field.key]}
              </p>
            )}
          </div>
        );
      })}
    </div>
  );
}
