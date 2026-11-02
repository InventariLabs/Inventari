import { useTranslation } from "react-i18next";
import { NativeSelect } from "@/components/ui/NativeSelect";
import { InlineQueryError } from "@/components/ui/QueryResult";
import { getCategoryLabel } from "@/modules/equipment/components/assetUtils";
import { LocationCombobox } from "@/module-sdk";
import type { CategoryDTO } from "@/types";

interface FilterProps<T> {
  value: string;
  onChange: (value: string) => void;
  options: T[];
  /** The list's error when it never arrived: the select gives way to a retry. */
  error: unknown;
  onRetry: () => unknown;
}

/**
 * The asset list's location filter: the module's own places, searched on the
 * server as the reader types. A search that failed says so in the panel
 * instead of reading as an organization with no locations.
 */
export function LocationFilter({
  value,
  onChange,
}: {
  value: string;
  onChange: (value: string) => void;
}) {
  const { t } = useTranslation("equipment");
  return (
    <LocationCombobox
      // The filter bar's controls are 12 px text; the field keeps its own
      // look, the width keeps it from taking the row.
      wrapperClassName="w-56"
      scope={{ moduleScope: "equipment" }}
      value={value}
      onChange={onChange}
      aria-label={t("list.filter_by_location", "Filter by location")}
      title={t("list.filter_by_location", "Filter by location")}
      placeholder={t("list.all_locations", "All Locations")}
      clearable
      clearLabel={t("list.all_locations", "All Locations")}
    />
  );
}

/** The asset list's category filter — equipment's own categories and untagged ones. */
export function CategoryFilter({
  value,
  onChange,
  options,
  error,
  onRetry,
}: FilterProps<CategoryDTO>) {
  const { t } = useTranslation("equipment");
  if (error)
    return <InlineQueryError error={error} onRetry={() => void onRetry()} />;
  return (
    <NativeSelect
      value={value}
      aria-label={t("list.filter_by_category", "Filter by category")}
      onChange={(e) => onChange(e.target.value)}
      className="text-xs"
    >
      <option value="">{t("list.all_categories", "All Categories")}</option>
      {options
        .filter((c) => c.context_tag === "equipment" || !c.context_tag)
        .map((c) => (
          <option key={c.id} value={c.id}>
            {getCategoryLabel(t, { code: c.code, name: c.name })}
          </option>
        ))}
    </NativeSelect>
  );
}
