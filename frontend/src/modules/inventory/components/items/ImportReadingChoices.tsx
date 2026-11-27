import { useTranslation } from "react-i18next";
import { Checkbox } from "@/components/ui/Checkbox";
import { ChoiceGroup } from "@/components/ui/ChoiceGroup";
import type { ImportMapping } from "@/components/import/types";
import type { LocationSlash } from "@/lib/api/items";
import { stockColumns } from "./importMapping";

export interface SheetReading {
  /** Whether "/" in a location divides a path or belongs to the name. */
  locationSlash: LocationSlash;
  /** A sheet with no quantity column: one of each, instead of products only. */
  countAsOne: boolean;
}

interface Props {
  headers: string[];
  mapping: ImportMapping;
  setMapping: (mapping: ImportMapping) => void;
  reading: SheetReading;
  onChange: (reading: SheetReading) => void;
}

/** How the import reads what a column cannot say by itself: stock held in a
 *  column per location, a sheet with no quantity, a slash in a location and a
 *  category written as a path. Each is shown only where the file raises it. */
export function ImportReadingChoices({
  headers,
  mapping,
  setMapping,
  reading,
  onChange,
}: Props) {
  const { t } = useTranslation(["items"]);
  const perLocation = stockColumns(headers);
  const columns = Object.values(perLocation);
  const readsPerLocation = Object.keys(perLocation).some((key) => mapping[key]);

  const togglePerLocation = (read: boolean) =>
    setMapping({
      ...mapping,
      ...Object.fromEntries(
        Object.entries(perLocation).map(([key, column]) => [
          key,
          read ? column : "",
        ]),
      ),
    });

  return (
    <div className="px-2 space-y-4">
      {columns.length > 0 && (
        <Checkbox
          checked={readsPerLocation}
          onChange={(e) => togglePerLocation(e.target.checked)}
          className="w-5 h-5 rounded-lg"
          label={
            <span className="text-sm text-on-secondary">
              {t("items:import.reading.perLocation", {
                columns: columns.join(", "),
              })}
            </span>
          }
        />
      )}
      {!mapping.quantity && !readsPerLocation && (
        <div>
          <ChoiceGroup
            label={t("items:import.reading.noQuantity.label")}
            layout="grid2"
            options={[
              {
                id: "products",
                label: t("items:import.reading.noQuantity.products"),
              },
              { id: "one", label: t("items:import.reading.noQuantity.one") },
            ]}
            value={reading.countAsOne ? "one" : "products"}
            onChange={(id) =>
              onChange({ ...reading, countAsOne: id === "one" })
            }
          />
          <p className="mt-2 text-sm text-on-secondary">
            {reading.countAsOne
              ? t("items:import.reading.noQuantity.oneNote")
              : t("items:import.reading.noQuantity.productsNote")}
          </p>
        </div>
      )}
      {(mapping.location || mapping.sublocation) && (
        <ChoiceGroup
          label={t("items:import.reading.slash.label")}
          hint={t("items:import.reading.slash.hint")}
          layout="grid2"
          options={[
            { id: "path", label: t("items:import.reading.slash.path") },
            { id: "name", label: t("items:import.reading.slash.name") },
          ]}
          value={reading.locationSlash}
          onChange={(id) =>
            onChange({ ...reading, locationSlash: id as LocationSlash })
          }
        />
      )}
      {mapping.category && (
        <p className="text-sm text-on-secondary">
          {t("items:import.reading.categoryPath")}
        </p>
      )}
    </div>
  );
}
