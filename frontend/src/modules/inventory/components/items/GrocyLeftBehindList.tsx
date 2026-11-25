import { useTranslation } from "react-i18next";
import type { components } from "@/module-sdk";

type LeftBehind = components["schemas"]["ImportLeftBehind"];

/** Each kind's words, named in full so the unused-key gate sees them read. */
const LABELS: Record<LeftBehind["what"], string> = {
  inactive_products: "items:import.grocyMove.leftBehind.inactive_products",
  extra_barcodes: "items:import.grocyMove.leftBehind.extra_barcodes",
  unit_conversions: "items:import.grocyMove.leftBehind.unit_conversions",
  units_as_pieces: "items:import.grocyMove.leftBehind.units_as_pieces",
  prices_below_a_cent: "items:import.grocyMove.leftBehind.prices_below_a_cent",
  default_best_before_days:
    "items:import.grocyMove.leftBehind.default_best_before_days",
  pictures: "items:import.grocyMove.leftBehind.pictures",
  parent_products: "items:import.grocyMove.leftBehind.parent_products",
  own_field_values: "items:import.grocyMove.leftBehind.own_field_values",
  recipes: "items:import.grocyMove.leftBehind.recipes",
  meal_plan: "items:import.grocyMove.leftBehind.meal_plan",
  chores: "items:import.grocyMove.leftBehind.chores",
  batteries: "items:import.grocyMove.leftBehind.batteries",
  tasks: "items:import.grocyMove.leftBehind.tasks",
  equipment: "items:import.grocyMove.leftBehind.equipment",
};

interface Props {
  entries: LeftBehind[];
}

/** What a Grocy file holds that the move does not bring, kind by kind with
 *  its count — said before the move and again in its summary, never dropped
 *  in silence. A unit nothing here matched is named, since its stock comes
 *  across counted in pieces. */
export function GrocyLeftBehindList({ entries }: Props) {
  const { t } = useTranslation(["items"]);
  if (entries.length === 0) return null;
  return (
    <div>
      <p className="text-[10px] font-medium text-on-muted uppercase tracking-widest mb-1">
        {t("items:import.grocyMove.stays")}
      </p>
      <ul className="text-xs text-on space-y-0.5">
        {entries.map((entry) => (
          <li key={entry.what} className="flex justify-between gap-4">
            <span>
              {t(LABELS[entry.what])}
              {entry.names.length > 0 && `: ${entry.names.join(", ")}`}
            </span>
            <span className="tabular-nums text-on-secondary">
              {entry.count}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}
