import type { TFunction } from "i18next";
import { useTranslation } from "react-i18next";
import { Card } from "@/components/ui/Card";
import { JournalCard, type JournalEntry } from "@/components/ui/JournalCard";
import { QueryFailure } from "@/components/ui/QueryResult";
import { formatDecimalQty, formatRecentMoment } from "@/utils/formatters";
import { formatQuantityLocalized } from "@/lib/i18nHelpers";
import type { StockMoveRow } from "@/lib/api/stockMoves";
import { useStockMoves } from "@/modules/inventory/hooks/useStockMoves";
import { useEnabledModulesOptional } from "@/contexts/ModulesContext";
import { recordsMovements } from "@/modules/inventory/constants/movementModules";
import { useShowModuleData } from "@/modules/settings/hooks/useOrganization";

/** How many moves the overview shows; the journal holds the rest. */
export const RECENT_MOVES_LIMIT = 5;

/**
 * The phrase for goods that appeared on a shelf. "Received" is a delivery; a
 * number corrected upwards on the record, or flour put back after cooking,
 * is not one, and reading them alike hid where the stock came from.
 */
function inboundPhrase(
  move: StockMoveRow,
  t: TFunction,
  quantity: string,
  to: string,
): string {
  if (move.reference_type === "item")
    return t("common:dashboard.journal.inByHand", { quantity, to });
  if (move.reference_type === "recipe_picking")
    return t("common:dashboard.journal.cookingIn", { quantity, to });
  return t("common:dashboard.journal.in", { quantity, to });
}

/** The phrase for goods that left: cooking says so rather than "issued". */
function outboundPhrase(
  move: StockMoveRow,
  t: TFunction,
  quantity: string,
  from: string,
): string {
  if (move.reference_type === "recipe_picking")
    return t("common:dashboard.journal.cookingOut", { quantity, from });
  return t("common:dashboard.journal.out", { quantity, from });
}

/**
 * One ledger row as a journal sentence. Direction is the shape of the pair
 * of locations, the same rule the ledger's own direction filter applies: no
 * origin came in from outside, no destination left, both moved inside.
 */
function moveJournalEntry(
  move: StockMoveRow,
  t: TFunction,
  now?: Date,
): JournalEntry {
  const quantity = formatQuantityLocalized(
    t,
    formatDecimalQty(move.quantity),
    move.uom_symbol,
  );
  // The outside is declined by the slot it fills: what came in "from
  // outside" did not also leave "from outside".
  const from = move.from_location_name ?? t("inventory:moves.outsideFrom");
  const to = move.to_location_name ?? t("inventory:moves.outsideTo");
  const at = move.completed_at ?? move.created_at ?? null;

  const [tone, phrase]: [JournalEntry["tone"], string] = !move.from_location_id
    ? ["success", inboundPhrase(move, t, quantity, to)]
    : !move.to_location_id
      ? ["warning", outboundPhrase(move, t, quantity, from)]
      : ["info", t("common:dashboard.journal.moved", { quantity, from, to })];

  return {
    id: move.id,
    tone,
    text: (
      <>
        <strong>{move.product_name ?? "—"}</strong> {phrase}
      </>
    ),
    timeLabel: formatRecentMoment(at, now),
    dateTime: at ?? undefined,
  };
}

/** The last few moves of the ledger, on the inventory overview. */
export function DashboardRecentMoves() {
  const { t } = useTranslation(["common", "inventory"]);
  // The overview counts what the products list shows, and so does its
  // journal: a laptop received into the equipment module is not a move here.
  const excludeModuleContexts = !useShowModuleData();
  // The journal screen is listed only where a module reads the ledger; the
  // overview must not link to a tab the navigation hides.
  const hasJournal = recordsMovements(useEnabledModulesOptional());
  const { data, isLoading, isError, error, refetch } = useStockMoves({
    limit: RECENT_MOVES_LIMIT,
    exclude_module_contexts: excludeModuleContexts,
  });

  if (isError) {
    return (
      <Card className="p-4 sm:p-5">
        <QueryFailure error={error} onRetry={() => void refetch()} />
      </Card>
    );
  }

  return (
    <JournalCard
      title={t("common:dashboard.journal.title")}
      entries={(data?.items ?? []).map((move) => moveJournalEntry(move, t))}
      linkLabel={hasJournal ? t("common:dashboard.journal.link") : undefined}
      linkHref={hasJournal ? "/inventory/moves" : undefined}
      loading={isLoading}
      empty={{
        text: t("common:dashboard.journal.empty"),
        linkLabel: t("common:dashboard.journal.emptyLink"),
        linkHref: "/inventory/items",
      }}
    />
  );
}
