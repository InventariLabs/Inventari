import { useTranslation } from "react-i18next";
import type { StockMoveRow } from "@/lib/api/stockMoves";
import { LOCATION_PATH_SEPARATOR } from "@/utils/helpers";

/** How a movement of a location carried with its stock reads, or `null`. */
export interface RelocationReading {
  from: string;
  to: string;
  kind: string;
}

/**
 * The route and the source of a row a physical location move wrote.
 *
 * Such a row names the same shelf on both ends — the location kept its id —
 * so the route the other rows read, shelf to shelf, would say nothing moved.
 * The row reads the location's own path before and after instead ("Main
 * Warehouse › Cold Storage → Pantry Building › Cold Storage"): its document
 * keeps the paths of the parents it left and reached, and a location at the
 * top level has its name alone. The source names the location that was
 * carried ("Moved with Cold Storage"). Shared by the table and the card list,
 * which are two readings of the same register.
 */
export function useRelocationReading(): (
  move: StockMoveRow,
) => RelocationReading | null {
  const { t } = useTranslation("inventory");
  return (move) => {
    if (move.reference_type !== "location_relocation") return null;
    const topLevel = t("inventory:moves.topLevel");
    const name = move.relocated_location_name;
    const at = (parentPath: string | null | undefined) => {
      if (!name) return parentPath ?? topLevel;
      return parentPath
        ? `${parentPath}${LOCATION_PATH_SEPARATOR}${name}`
        : name;
    };
    return {
      from: at(move.relocated_from_path),
      to: at(move.relocated_to_path),
      kind: move.relocated_location_name
        ? t("inventory:moves.movedWith", {
            name: move.relocated_location_name,
          })
        : t("inventory:moves.source.location_relocation"),
    };
  };
}
