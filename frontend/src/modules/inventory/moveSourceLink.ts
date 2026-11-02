/**
 * Where a movement's source lives, when the app has a page for it.
 *
 * The SOURCE column names the *kind* of thing a movement came from — "Stock
 * take", "Document", "Production" — and the row carries `reference_id`, the
 * thing itself, which the screen did not use. So somebody asking "why did the
 * yoghurt go down" was told "from a stock take" with no way to reach *which*
 * stock take, or the reason typed on it. The register's own subtitle promises
 * to explain a movement, and the warehouse module's purpose card puts it
 * plainly: "so that months later somebody can be shown why the numbers are
 * what they are".
 *
 * Not every kind has a page. `item_history` points at a row of the one-time
 * ItemHistory backfill, which nothing renders; that badge stays a badge
 * rather than becoming a link to a wall. The map below is exhaustive over
 * `StockMoveReferenceType` and `moveSourceVocabulary.test.ts` holds it to
 * that, so a sixth kind cannot quietly fall through as "leads nowhere".
 */

import { useModules } from "@/contexts/ModulesContext";

/** A page for one movement's source, and the module that has to be on for it. */
export interface MoveSourceTarget {
  path: string;
  /** Undefined for a page the Core always serves. */
  module?: string;
}

type Destination = ((id: string) => MoveSourceTarget) | null;

/** Exhaustive over `StockMoveReferenceType` — `null` means "no page for it". */
export const MOVE_SOURCE_DESTINATIONS: Record<string, Destination> = {
  document: (id) => ({
    path: `/warehouse/documents/${id}`,
    module: "warehouse",
  }),
  item: (id) => ({ path: `/inventory/items/${id}` }),
  adjustment: (id) => ({ path: `/inventory/stock-takes/${id}/report` }),
  maker_production: (id) => ({
    path: `/maker/production/${id}`,
    module: "maker",
  }),
  // A picking session: the cooking is told on the recipe, and no screen
  // opens one session of it.
  recipe_picking: null,
  // The backfill's own rows: an ItemHistory id, and no screen shows one.
  item_history: null,
  // The stock a shelf held before the register knew it: posted by a
  // migration, on no one's instruction, so there is nothing to open.
  opening_balance: null,
  // A location carried with its stock: the row names its document's paths
  // itself, and no screen opens one relocation.
  location_relocation: null,
};

/**
 * The page for this movement's source, or `null` when there is none to offer.
 *
 * `null` for a kind with no page, for a row that carries no reference, and for
 * a kind this build does not know — a row that leads nowhere shows the plain
 * badge rather than a link that cannot be followed. Reached through
 * `useMoveSourceLink`, which also asks whether the module is switched on.
 */
function moveSourceTarget(
  referenceType: string | null | undefined,
  referenceId: string | null | undefined,
): MoveSourceTarget | null {
  if (!referenceType || !referenceId) return null;
  const destination = MOVE_SOURCE_DESTINATIONS[referenceType];
  return destination ? destination(referenceId) : null;
}

/**
 * The href for a movement's source, or `null` when the register cannot offer
 * one — no page for that kind, no reference on the row, or the module that
 * owns the page switched off. Shared by the table and the card list, which
 * are two readings of the same register and must answer alike.
 */
export function useMoveSourceLink(): (move: {
  reference_type?: string | null;
  reference_id?: string | null;
}) => string | null {
  const { isModuleEnabled } = useModules();
  return (move) => {
    const target = moveSourceTarget(move.reference_type, move.reference_id);
    if (!target) return null;
    // A badge that leads to the "this module is switched off" wall explains
    // less than a badge.
    if (target.module && !isModuleEnabled(target.module)) return null;
    return target.path;
  };
}
