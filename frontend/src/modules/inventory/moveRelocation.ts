import { useTranslation } from "react-i18next";
import type { StockMoveRow } from "@/lib/api/stockMoves";

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
 * The row carries its document's paths instead ("Main Warehouse → Pantry
 * Building"), and the source names the location that was carried ("Moved
 * with Cold Storage"). Shared by the table and the card list, which are two
 * readings of the same register.
 */
export function useRelocationReading(): (
  move: StockMoveRow,
) => RelocationReading | null {
  const { t } = useTranslation("inventory");
  return (move) => {
    if (move.reference_type !== "location_relocation") return null;
    const topLevel = t("inventory:moves.topLevel");
    return {
      from: move.relocated_from_path ?? topLevel,
      to: move.relocated_to_path ?? topLevel,
      kind: move.relocated_location_name
        ? t("inventory:moves.movedWith", {
            name: move.relocated_location_name,
          })
        : t("inventory:moves.source.location_relocation"),
    };
  };
}
