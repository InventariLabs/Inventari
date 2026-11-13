/**
 * The movement ledger as a table — the desktop reading.
 *
 * A list of records is a `<table>` (UI_GUIDELINES §14.1): a grid of divs
 * gives a sighted reader columns and a screen reader nothing. The ledger is
 * always ordered by when the goods moved, so that column — and only that one
 * — carries `aria-sort`.
 */
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import { ArrowRight } from "lucide-react";
import { Badge } from "@/components/ui/Badge";
import { formatDateTime } from "@/utils/helpers";
import { formatDateMedium, formatDecimalQty } from "@/utils/formatters";
import { formatQuantityLocalized } from "@/lib/i18nHelpers";
import { useModules } from "@/contexts/ModulesContext";
import { useDocumentNumbers } from "@/modules/inventory/hooks/useDocumentNumbers";
import { useMoveSourceLink } from "@/modules/inventory/moveSourceLink";
import { useRelocationReading } from "@/modules/inventory/moveRelocation";
import type { StockMoveRow } from "@/lib/api/stockMoves";
import { useStorageLocationLabels } from "@/modules/shared/hooks/useStorageLocationLabels";

interface StockMovesTableProps {
  moves: StockMoveRow[];
  /** False on a product's own card, where the column would repeat one name. */
  showProduct?: boolean;
}

/** The place a movement came from or went to, or the world outside. */
function Place({ name, outside }: { name: string | null; outside: string }) {
  if (name) return <span className="text-on">{name}</span>;
  return <span className="text-on-muted italic">{outside}</span>;
}

export function StockMovesTable({
  moves,
  showProduct = true,
}: StockMovesTableProps) {
  const { t } = useTranslation(["inventory", "common"]);
  const sourceLink = useMoveSourceLink();
  const placeName = useStorageLocationLabels(
    moves.flatMap((move) => [move.from_location_id, move.to_location_id]),
  );
  const relocation = useRelocationReading();
  const { isModuleEnabled } = useModules();
  // A source badge that says "Document" answers the kind; the recall
  // question is "which one". The register names the rows shown here in one
  // ask — and is asked at all only when it is there to answer.
  const documentNumbers = useDocumentNumbers(
    moves.map((move) =>
      move.reference_type === "document" ? move.reference_id : null,
    ),
    isModuleEnabled("warehouse"),
  );

  return (
    <div className="bg-surface-card rounded-xl sm:rounded-2xl shadow-sm border border-border overflow-hidden">
      <div className="overflow-x-auto">
        <table className="w-full text-left border-collapse">
          <thead>
            <tr className="bg-surface-raised border-b border-border text-xs font-medium text-on-secondary uppercase tracking-wider">
              <th scope="col" className="px-4 py-3" aria-sort="descending">
                {t("inventory:moves.columns.when")}
              </th>
              {showProduct && (
                <th scope="col" className="px-4 py-3">
                  {t("inventory:moves.columns.product")}
                </th>
              )}
              <th scope="col" className="px-4 py-3 text-right">
                {t("inventory:moves.columns.quantity")}
              </th>
              <th scope="col" className="px-4 py-3">
                {t("inventory:moves.columns.route")}
              </th>
              <th scope="col" className="px-4 py-3">
                {t("inventory:moves.columns.batch")}
              </th>
              <th scope="col" className="px-4 py-3">
                {t("inventory:moves.columns.source")}
              </th>
              <th scope="col" className="px-4 py-3">
                {t("inventory:moves.columns.who")}
              </th>
            </tr>
          </thead>
          <tbody>
            {moves.map((move) => (
              <tr
                key={move.id}
                className="border-b border-border last:border-0 text-sm hover:bg-surface-raised/50"
              >
                <td className="px-4 py-2.5 whitespace-nowrap text-on-secondary">
                  {formatDateTime(move.completed_at ?? move.created_at ?? "")}
                </td>
                {showProduct && (
                  <td className="px-4 py-2.5 text-on">
                    {move.product_name ?? "—"}
                  </td>
                )}
                <td className="px-4 py-2.5 text-right tabular-nums text-on whitespace-nowrap">
                  {/* The column serialises at full scale ("3.000"), and the
                      symbol on the row is the canonical one — printing either
                      verbatim claims a precision nobody typed and a unit
                      nobody translated. */}
                  {formatQuantityLocalized(
                    t,
                    formatDecimalQty(move.quantity),
                    move.uom_symbol,
                  )}
                </td>
                <td className="px-4 py-2.5">
                  <span className="inline-flex items-center gap-1.5 whitespace-nowrap">
                    <Place
                      name={
                        relocation(move)?.from ??
                        placeName(
                          move.from_location_id,
                          move.from_location_name,
                        )
                      }
                      outside={t("inventory:moves.outsideFrom")}
                    />
                    <ArrowRight
                      size={14}
                      className="text-on-muted shrink-0"
                      aria-hidden="true"
                    />
                    <Place
                      name={
                        relocation(move)?.to ??
                        placeName(move.to_location_id, move.to_location_name)
                      }
                      outside={t("inventory:moves.outsideTo")}
                    />
                  </span>
                </td>
                <td className="px-4 py-2.5 text-on-secondary">
                  {/* The batch is the one column that leads somewhere: a
                      recall starts by clicking the number it was given. */}
                  {move.lot_id && move.lot_name ? (
                    <Link
                      to={`/inventory/lots/${move.lot_id}`}
                      className="text-on-primary hover:underline"
                    >
                      {move.lot_name}
                    </Link>
                  ) : (
                    (move.lot_name ?? "—")
                  )}
                  {move.expiry_date && (
                    <span className="block text-xs text-on-muted">
                      {t("inventory:moves.expires", {
                        date: formatDateMedium(move.expiry_date),
                      })}
                    </span>
                  )}
                </td>
                <td className="px-4 py-2.5">
                  {/* The kind of thing and the thing itself: the badge names
                      the source — by its number, when the register answered
                      for the rows shown — and where the app has a page for
                      that source, the badge leads to it. */}
                  {move.reference_type ? (
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
                  ) : (
                    <span className="text-on-muted">—</span>
                  )}
                </td>
                <td className="px-4 py-2.5 text-on-secondary">
                  {move.user_name ?? "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
