import { useTranslation } from "react-i18next";
import type { ItemImportOutcome } from "@/components/import/types";
import { GrocyLeftBehindList } from "./GrocyLeftBehindList";
import { ImportFoundedList } from "./ImportFoundedList";

interface Props {
  result: ItemImportOutcome;
  /** The result is a move from Grocy's file, not a sheet's rows: what it
   *  skipped was already here from an earlier move, not a label code's
   *  product the reader chose to leave alone. */
  fromGrocy: boolean;
}

/** What an import did beside the products: what it left alone, what it
 *  created on the way, what other modules brought from the same file, and
 *  what stayed where it came from — so the reader learns it here and not
 *  from new tiles later. Nothing is shown when there is none of it. */
export function ImportResultDetails({ result, fromGrocy }: Props) {
  const { t } = useTranslation(["items"]);
  const anything =
    result.skipped > 0 ||
    result.created_locations.length > 0 ||
    result.created_categories.length > 0 ||
    result.created_suppliers.length > 0 ||
    result.brought_by_modules.length > 0 ||
    result.left_behind.length > 0;
  if (!anything) return null;
  return (
    <div className="bg-surface p-6 rounded-xl border border-border text-left max-w-md mx-auto space-y-3">
      {result.skipped > 0 && (
        <p className="text-xs text-on">
          {fromGrocy
            ? t("items:import.grocyMove.skipped", { count: result.skipped })
            : t("items:import.matchedSkipped", { count: result.skipped })}
        </p>
      )}
      <ImportFoundedList
        heading={t("items:import.foundedLocations", {
          count: result.created_locations.length,
        })}
        names={result.created_locations}
      />
      <ImportFoundedList
        heading={t("items:import.foundedCategories", {
          count: result.created_categories.length,
        })}
        names={result.created_categories}
      />
      <ImportFoundedList
        heading={t("items:import.grocyMove.foundedSuppliers", {
          count: result.created_suppliers.length,
        })}
        names={result.created_suppliers}
      />
      {/* What other modules brought from the same file, in their own words
          (the shopping lists, say). */}
      {result.brought_by_modules.map((brought) => (
        <p key={brought.module} className="text-xs text-on">
          {brought.sentence}
        </p>
      ))}
      <GrocyLeftBehindList entries={result.left_behind} />
    </div>
  );
}
