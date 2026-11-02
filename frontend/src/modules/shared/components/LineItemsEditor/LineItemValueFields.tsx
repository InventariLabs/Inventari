import { Input } from "@/components/ui/Input";
import type {
  LineItem,
  LineItemsEditorFeatures,
  LineItemsEditorLabels,
} from "./types";

interface LineItemValueFieldsProps {
  line: LineItem;
  features: LineItemsEditorFeatures;
  labels: LineItemsEditorLabels;
  unitPriceFieldId: string;
  taxRateFieldId: string;
  lineValue: string;
  onUpdate: (updates: Partial<LineItem>) => void;
}

export function LineItemValueFieldsDesktop({
  line,
  features,
  labels,
  unitPriceFieldId,
  taxRateFieldId,
  lineValue,
  onUpdate,
}: LineItemValueFieldsProps) {
  return (
    <>
      <Input
        id={unitPriceFieldId}
        type="number"
        min={0}
        step="0.01"
        label={labels.unitPrice}
        value={line.unit_price ?? ""}
        onChange={(e) => onUpdate({ unit_price: e.target.value })}
        className="h-10 px-2 text-right"
        wrapperClassName="hidden xl:block xl:space-y-0"
        labelClassName="xl:sr-only"
      />
      {features.taxField && (
        <Input
          id={taxRateFieldId}
          type="number"
          min={0}
          max={100}
          step="0.01"
          label={labels.taxRate}
          placeholder={labels.taxRatePlaceholder}
          value={line.tax_rate ?? ""}
          onChange={(e) => onUpdate({ tax_rate: e.target.value })}
          className="h-10 px-2 text-right"
          wrapperClassName="hidden xl:block xl:space-y-0"
          labelClassName="xl:sr-only"
        />
      )}
      <div className="hidden xl:flex xl:items-center xl:justify-end xl:h-10 xl:px-2 xl:text-sm xl:font-mono xl:text-on">
        {lineValue || "—"}
      </div>
    </>
  );
}

export function LineItemValueFieldsMobile({
  line,
  features,
  labels,
  unitPriceFieldId,
  taxRateFieldId,
  lineValue,
  onUpdate,
}: LineItemValueFieldsProps) {
  return (
    <div className="mt-3 grid grid-cols-2 items-end gap-3 sm:grid-cols-3 xl:hidden">
      <Input
        id={`${unitPriceFieldId}-mobile`}
        type="number"
        min={0}
        step="0.01"
        label={labels.unitPrice}
        value={line.unit_price ?? ""}
        onChange={(e) => onUpdate({ unit_price: e.target.value })}
        className="h-10 px-2"
      />
      {features.taxField && (
        <Input
          id={`${taxRateFieldId}-mobile`}
          type="number"
          min={0}
          max={100}
          step="0.01"
          label={labels.taxRate}
          placeholder={labels.taxRatePlaceholder}
          value={line.tax_rate ?? ""}
          onChange={(e) => onUpdate({ tax_rate: e.target.value })}
          className="h-10 px-2"
        />
      )}
      {lineValue && (
        <div className="space-y-1.5">
          <span className="text-xs font-medium uppercase text-on-secondary ml-1 tracking-wide block">
            {labels.lineValue}
          </span>
          <div className="h-10 flex items-center px-2 text-sm font-mono text-on">
            {lineValue}
          </div>
        </div>
      )}
    </div>
  );
}
