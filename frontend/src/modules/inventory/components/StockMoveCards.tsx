/**
 * The movement ledger on a phone — one card a movement.
 *
 * The desktop table is built for reading many rows at once; on a narrow
 * screen the same seven columns would wrap into gibberish, so the card branch
 * says the same things in a sentence order instead (UI_GUIDELINES §14.1).
 */
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import { ArrowRight } from "lucide-react";
import { Badge } from "@/components/ui/Badge";
import { useModules } from "@/contexts/ModulesContext";
import { useDocumentNumbers } from "@/modules/inventory/hooks/useDocumentNumbers";
import { useMoveSourceLink } from "@/modules/inventory/moveSourceLink";
import { useRelocationReading } from "@/modules/inventory/moveRelocation";
import { formatDateTime } from "@/utils/helpers";
import { formatDateMedium, formatDecimalQty } from "@/utils/formatters";
import { formatQuantityLocalized } from "@/lib/i18nHelpers";
import type { StockMoveRow } from "@/lib/api/stockMoves";
import { useStorageLocationLabels } from "@/modules/shared/hooks/useStorageLocationLabels";

interface StockMoveCardsProps {
  moves: StockMoveRow[];
  /** False on a product's own card — the header already names the product. */
  showProduct?: boolean;
}

export function StockMoveCards({
  moves,
  showProduct = true,
}: StockMoveCardsProps) {
  const { t } = useTranslation(["inventory", "common"]);
  const sourceLink = useMoveSourceLink();
  const placeName = useStorageLocationLabels(
    moves.flatMap((move) => [move.from_location_id, move.to_location_id]),
  );
  const relocation = useRelocationReading();
  const { isModuleEnabled } = useModules();
  // The same naming the table does: a source badge says "which one", not
  // only the kind — one ask to the register for the page's rows.
  const documentNumbers = useDocumentNumbers(
    moves.map((move) =>
      move.reference_type === "document" ? move.reference_id : null,
    ),
    isModuleEnabled("warehouse"),
  );
  // The world outside is declined by the end of the arrow it fills; a word
  // meaning "from outside" on the destination end reads every issue as an
  // arrival.
  const outsideFrom = t("inventory:moves.outsideFrom");
  const outsideTo = t("inventory:moves.outsideTo");

  return (
    <ul className="space-y-3">
      {moves.map((move) => (
        <li
          key={move.id}
          className="bg-surface-card rounded-xl shadow-sm border border-border p-4 space-y-2"
        >
          <div className="flex items-start justify-between gap-3">
            {/* Something has to anchor the card. Where the product is a
                given, the date is what tells one movement from the next. */}
            <span className="font-medium text-on">
              {showProduct
                ? (move.product_name ?? "—")
                : formatDateTime(move.completed_at ?? move.created_at ?? "")}
            </span>
            <span className="tabular-nums text-on whitespace-nowrap">
              {formatQuantityLocalized(
                t,
                formatDecimalQty(move.quantity),
                move.uom_symbol,
              )}
            </span>
          </div>
          <div className="flex items-center gap-1.5 text-sm text-on-secondary">
            <span>
              {relocation(move)?.from ??
                placeName(move.from_location_id, move.from_location_name) ??
                outsideFrom}
            </span>
            <ArrowRight size={14} className="shrink-0" aria-hidden="true" />
            <span>
              {relocation(move)?.to ??
                placeName(move.to_location_id, move.to_location_name) ??
                outsideTo}
            </span>
          </div>
          <div className="flex flex-wrap items-center gap-2 text-xs text-on-muted">
            {/* Joined once, so dropping any one of them never leaves a
                separator hanging at the front of the line. */}
            <span>
              {[
                showProduct
                  ? formatDateTime(move.completed_at ?? move.created_at ?? "")
                  : null,
                move.lot_name,
                move.expiry_date
                  ? t("inventory:moves.expires", {
                      date: formatDateMedium(move.expiry_date),
                    })
                  : null,
                move.user_name,
              ]
                .filter(Boolean)
                .join(" · ")}
            </span>
            {move.reference_type
              ? // The same badge the table shows, leading to the same page —
                // the phone reading asks the same question of a movement.
                (() => {
                  const kind =
                    relocation(move)?.kind ??
                    t(`inventory:moves.source.${move.reference_type}`, {
                      defaultValue: move.reference_type,
                    });
                  const number =
                    move.reference_type === "document" && move.reference_id
                      ? documentNumbers.data?.[move.reference_id]
                      : undefined;
                  const href = sourceLink(move);
                  const badge = (
                    <Badge variant="secondary">{number ?? kind}</Badge>
                  );
                  if (!href) return badge;
                  return (
                    <Link
                      to={href}
                      className="inline-flex min-h-11 items-center md:min-h-8 hover:underline"
                      aria-label={number ? `${kind} ${number}` : kind}
                    >
                      {badge}
                    </Link>
                  );
                })()
              : null}
          </div>
        </li>
      ))}
    </ul>
  );
}
