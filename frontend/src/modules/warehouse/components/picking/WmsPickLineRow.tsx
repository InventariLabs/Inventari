import { memo } from "react";
import { useTranslation } from "react-i18next";
import {
  CheckCircle2,
  Clock,
  MinusCircle,
  RotateCcw,
  SkipForward,
  MapPin,
} from "lucide-react";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import type { WmsPickLine } from "@/modules/warehouse/api/documents";
import { unitLabel } from "@/lib/i18nHelpers";
import { formatDateMedium, formatQuantityValue } from "@/utils/formatters";
import ShelfConfirmation, {
  type ShelfConfirmationState,
} from "../ShelfConfirmation";

const statusVariant: Record<
  string,
  "success" | "warning" | "secondary" | "danger"
> = {
  picked: "success",
  pending: "secondary",
  short: "warning",
  skipped: "secondary",
};

interface Props {
  line: WmsPickLine;
  /** Names the line's document: a session over several dispatches. */
  showDocument?: boolean;
  /** Set when the session asks for the shelf's label before the product. */
  shelfState?: ShelfConfirmationState | null;
  /** Records the whole line, the way a receiving line takes its full amount. */
  onFullPick: (line: WmsPickLine) => void;
  onUndo: (line: WmsPickLine) => void;
  onShortPick: (line: WmsPickLine) => void;
  onSkip: (line: WmsPickLine) => void;
}

const WmsPickLineRow = memo(function WmsPickLineRow({
  line,
  showDocument = false,
  shelfState,
  onFullPick,
  onUndo,
  onShortPick,
  onSkip,
}: Props) {
  const { t } = useTranslation("warehouse");
  const variant = statusVariant[line.status] ?? "secondary";

  return (
    // A plain row, not a button: tapping it used to open the shortfall
    // sheet at 0, so recording an ordinary pick meant typing the number
    // the row already carried — one sheet and one keyboard per line. Every
    // action a pending line offers is a named button now, the way the
    // receiving row has them, and a thumb that lands here while scrolling
    // records nothing.
    //
    // Wraps: on a 320px sheet the name shared one row with the quantity,
    // the status badge and three icons and was left a few pixels, so the
    // figures drop under it instead.
    <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1.5 px-4 py-3 border-b border-border last:border-0">
      <div className="flex min-w-0 flex-1 basis-40 gap-2">
        {line.status === "picked" || line.status === "short" ? (
          <CheckCircle2 size={16} className="text-accent-500 shrink-0" />
        ) : (
          <Clock size={16} className="text-on-muted shrink-0" />
        )}
        <div className="min-w-0">
          {showDocument && line.document_number && (
            <p className="text-xs font-medium text-on-secondary truncate">
              {line.document_number}
            </p>
          )}
          <p className="text-sm font-medium text-on truncate">
            {line.product_name ?? t("picking.unknown_product")}
          </p>
          {line.bin_location && (
            <p className="text-xs text-on-muted flex items-center gap-0.5 truncate">
              <MapPin size={10} />
              {line.bin_location}
            </p>
          )}
          {shelfState && line.status === "pending" && (
            <ShelfConfirmation state={shelfState} kind="picking" />
          )}
          {line.lot_name && (
            <p className="text-xs text-on-muted truncate">
              {t("picking.lot", { name: line.lot_name })}
            </p>
          )}
          {/* The date of the pack the draw reaches first: the batch's, or
              the record's own where the stock carries no batch. */}
          {line.expiry_date && (
            <p className="text-xs text-on-muted truncate">
              {t("picking.expires", {
                date: formatDateMedium(line.expiry_date),
              })}
            </p>
          )}
        </div>
      </div>

      <div className="ml-auto flex items-center gap-2 shrink-0">
        <span className="text-xs text-on-secondary">
          {/* Once part of the line is in the session, the count is two
              numbers — what was scanned and what the document expects — the
              same pair the receiving row and the scan field above show. The
              row used to keep only the scanned count, while "Pick full
              amount" beside it booked the whole expectation. */}
          {line.picked_quantity > 0
            ? `${formatQuantityValue(line.picked_quantity)}/${formatQuantityValue(line.expected_quantity)}`
            : formatQuantityValue(line.expected_quantity)}{" "}
          {unitLabel(t, line.uom_symbol)}
        </span>
        {/* No `capitalize` — same reason as the recipes picking row: the
            dictionary's case is the correct one, and capitalizing every
            word breaks multi-word labels the day one appears. */}
        <Badge variant={variant}>{t(`picking.status.${line.status}`)}</Badge>

        {line.status === "pending" && (
          <div className="flex items-center gap-1">
            {/* The whole line in one tap, named like the two beside it —
                the receiving row's "Receive full amount". The number is
                the document's own expectation, which the row already
                shows: before this, a full pick was the shortfall sheet at
                0 with the quantity typed in by hand. */}
            <Button
              type="button"
              onClick={() => onFullPick(line)}
              variant="ghost"
              size="icon"
              className="rounded text-accent-600 hover:bg-accent-50 active:bg-accent-50"
              title={t("picking.full_pick")}
              aria-label={t("picking.full_pick")}
            >
              <CheckCircle2 size={16} />
            </Button>
            <Button
              type="button"
              onClick={() => onShortPick(line)}
              variant="ghost"
              size="icon"
              className="rounded text-amber-500 hover:bg-amber-50"
              title={t("picking.short_pick")}
              aria-label={t("picking.short_pick")}
            >
              <MinusCircle size={16} />
            </Button>
            {/* The shortfall form and an explicit skip, side by side: a
                line that cannot be fully served leaves the session through
                one of the two. skipLine's prop existed before the button
                did — it was reachable only from inside the short-pick
                dialog, one click deeper than its receiving twin. */}
            <Button
              type="button"
              onClick={() => onSkip(line)}
              variant="ghost"
              size="icon"
              className="rounded text-on-muted hover:bg-surface-inset"
              title={t("picking.skip_line")}
              aria-label={t("picking.skip_line")}
            >
              <SkipForward size={16} />
            </Button>
          </div>
        )}

        {/* A skipped line stays on the list for the same reason: the skip
            was one tap, so taking it back is one tap too. */}
        {(line.status === "picked" ||
          line.status === "short" ||
          line.status === "skipped") && (
          <Button
            type="button"
            onClick={() => onUndo(line)}
            variant="ghost"
            size="icon"
            className="rounded text-on-muted hover:bg-surface-inset"
            title={t("picking.undo_action")}
            aria-label={t("picking.undo_action")}
          >
            <RotateCcw size={16} />
          </Button>
        )}
      </div>
    </div>
  );
});

export default WmsPickLineRow;
