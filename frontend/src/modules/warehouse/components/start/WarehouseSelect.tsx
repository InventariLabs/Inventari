import { useTranslation } from "react-i18next";
import { NativeSelect } from "@/components/ui/NativeSelect";
import type { StorageLocationNode } from "@/types";

/**
 * The warehouse the screen is showing. It appears only when the
 * organization keeps more than one top-level location; with a single one
 * there is nothing to choose, and a control that cannot change anything is
 * noise. "All warehouses" keeps the whole organization in view.
 */
export function WarehouseSelect({
  warehouses,
  value,
  onChange,
}: {
  warehouses: StorageLocationNode[];
  value: string | null;
  onChange: (warehouseId: string | null) => void;
}) {
  const { t } = useTranslation("warehouse");
  return (
    <NativeSelect
      label={t("start.warehouse.label")}
      labelClassName="sr-only"
      wrapperClassName="w-full sm:w-56"
      value={value ?? ""}
      onChange={(event) => onChange(event.target.value || null)}
    >
      <option value="">{t("start.warehouse.all")}</option>
      {warehouses.map((warehouse) => (
        <option key={warehouse.id} value={warehouse.id}>
          {warehouse.name}
        </option>
      ))}
    </NativeSelect>
  );
}
