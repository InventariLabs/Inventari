import { useTranslation } from "react-i18next";
import type { GrocyFileAnalysis } from "@/lib/api/items";
import { GrocyLeftBehindList } from "./GrocyLeftBehindList";

interface Props {
  fileName: string;
  analysis: GrocyFileAnalysis;
  /** Grocy groups this screen recognised as categories already here; they
   *  are not created. */
  categoryMatches: Record<string, string>;
}

/** The step before a Grocy move: what the file holds, what the move would
 *  create, what an earlier move already brought, the currency the prices are
 *  read in, and what stays in Grocy. Nothing has been written yet. */
export function GrocyFileReview({
  fileName,
  analysis,
  categoryMatches,
}: Props) {
  const { t } = useTranslation(["items"]);
  const counts: [string, number][] = [
    [t("items:import.grocyMove.counts.products"), analysis.products],
    [t("items:import.grocyMove.counts.stockEntries"), analysis.stock_entries],
    [t("items:import.grocyMove.counts.locations"), analysis.locations],
    [t("items:import.grocyMove.counts.productGroups"), analysis.product_groups],
    [t("items:import.grocyMove.counts.stores"), analysis.stores],
    [
      t("items:import.grocyMove.counts.shoppingListEntries"),
      analysis.shopping_list_entries,
    ],
  ];
  const created = [
    {
      labelKey: "items:import.grocyMove.newLocations",
      names: analysis.new_locations,
    },
    {
      labelKey: "items:import.grocyMove.newCategories",
      names: analysis.new_categories.filter(
        (name) => !(name in categoryMatches),
      ),
    },
    {
      labelKey: "items:import.grocyMove.newSuppliers",
      names: analysis.new_suppliers,
    },
  ] as const;
  const creates = created.some((group) => group.names.length > 0);

  return (
    <div className="space-y-6 text-left">
      <div>
        <p className="text-[10px] font-medium text-on-muted uppercase tracking-widest mb-2">
          {t("items:import.grocyMove.inFile")} · {fileName}
        </p>
        <dl className="grid grid-cols-2 sm:grid-cols-3 gap-3">
          {counts.map(([label, value]) => (
            <div key={label} className="rounded-xl border border-border p-3">
              <dt className="text-xs text-on-secondary">{label}</dt>
              <dd className="text-lg font-medium text-on tabular-nums">
                {value}
              </dd>
            </div>
          ))}
        </dl>
      </div>

      {analysis.already_imported > 0 && (
        <p className="text-sm text-on-secondary">
          {t("items:import.grocyMove.alreadyImported", {
            count: analysis.already_imported,
          })}
        </p>
      )}

      {creates && (
        <div>
          <p className="text-[10px] font-medium text-on-muted uppercase tracking-widest mb-1">
            {t("items:import.grocyMove.willCreate")}
          </p>
          <ul className="text-sm text-on space-y-1">
            {created
              .filter((group) => group.names.length > 0)
              .map((group) => (
                <li key={group.labelKey}>
                  {t(group.labelKey, {
                    names: group.names.join(", "),
                  })}
                </li>
              ))}
          </ul>
        </div>
      )}

      {analysis.currency && (
        <p className="text-sm text-on-secondary">
          {t("items:import.grocyMove.currency", {
            currency: analysis.currency,
          })}
        </p>
      )}

      <GrocyLeftBehindList entries={analysis.left_behind} />
    </div>
  );
}
