import { useTranslation } from "react-i18next";
import { Select } from "@/components/ui/Select";

interface ColumnMapping {
  name: string;
  brand: string;
  barcode: string;
  sku: string;
  quantity: string;
  uom_symbol: string;
  unit_price: string;
  tax_rate: string;
  batch_number: string;
  expiry_date: string;
}

interface ColumnMappingFormProps {
  mapping: ColumnMapping;
  headers: string[];
  onChange: (field: keyof ColumnMapping, value: string) => void;
}

export function ColumnMappingForm({
  mapping,
  headers,
  onChange,
}: ColumnMappingFormProps) {
  const { t } = useTranslation("warehouse");

  const fields: {
    key: keyof ColumnMapping;
    label: string;
    required?: boolean;
  }[] = [
    {
      key: "name",
      label: t("import.name"),
      required: !mapping.sku && !mapping.barcode,
    },
    {
      key: "barcode",
      label: t("import.barcode", { defaultValue: "Barcode/EAN" }),
    },
    { key: "sku", label: t("import.sku", { defaultValue: "SKU" }) },
    { key: "brand", label: t("import.brand") },
    {
      key: "quantity",
      label: t("import.quantity", { defaultValue: "Quantity" }),
    },
    {
      key: "uom_symbol",
      label: t("import.uom"),
    },
    {
      key: "unit_price",
      label: t("import.unitPrice"),
    },
    // the importer has always read these three; the form simply never
    // offered them, so a spreadsheet carrying lot numbers and expiry dates had
    // to be retyped line by line.
    {
      key: "tax_rate",
      label: t("import.taxRate"),
    },
    {
      key: "batch_number",
      label: t("import.batchNumber"),
    },
    {
      key: "expiry_date",
      label: t("import.expiryDate"),
    },
  ];

  return (
    <div className="grid grid-cols-2 gap-3">
      {fields.map(({ key, label, required }) => (
        <div key={key}>
          <Select
            label={label}
            required={required}
            value={mapping[key]}
            onChange={(id) => onChange(key, id)}
            placeholder="--"
            options={headers.map((h) => ({ id: h, name: h }))}
          />
        </div>
      ))}
    </div>
  );
}
