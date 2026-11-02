import { useTranslation } from "react-i18next";
import { LocationCombobox } from "@/module-sdk";

/**
 * Where a returned asset goes — one field for the single and the bulk return.
 *
 * A checkout to a place shows the place while it lasts and leaves the asset's
 * own location, its home, in the record; the return puts it back there. The
 * field starts on that home, so a return that lands somewhere else is said at
 * the return instead of needing a separate Location action afterwards.
 *
 * The places are the module's own, searched on the server as the reader types.
 */
export function ReturnLocationField({
  value,
  onChange,
  leadingOption,
}: {
  value: string;
  onChange: (id: string) => void;
  /** The answer that names no place, e.g. "each to its own location". */
  leadingOption?: { id: string; name: string };
}) {
  const { t } = useTranslation("equipment");
  const none = leadingOption?.id;
  return (
    <LocationCombobox
      label={t("assignments.returns_to")}
      title={t("assignments.returns_to")}
      scope={{ moduleScope: "equipment" }}
      value={value === none ? "" : value}
      onChange={(id) => onChange(id || (none ?? ""))}
      placeholder={leadingOption?.name ?? t("bulk_edit.select_location")}
      clearable={leadingOption !== undefined}
      clearLabel={leadingOption?.name}
    />
  );
}
