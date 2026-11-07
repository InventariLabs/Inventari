import { useTranslation } from "react-i18next";
import {
  RotateCcw,
  MinusCircle,
  SkipForward,
  CheckCircle2,
} from "lucide-react";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { unitLabel } from "@/lib/i18nHelpers";
import type { WmsReceiveLine } from "@/modules/warehouse/api/documents_receiving";
import { floorPutaway } from "@/modules/warehouse/landedLocation";
import { ShelfSelect } from "@/modules/warehouse/components/LineTargetPicker";
import { cn } from "@/lib/utils";
import ShelfConfirmation, {
  type ShelfConfirmationState,
} from "../ShelfConfirmation";
import { formatQuantityLocale, formatQuantityValue } from "@/utils/formatters";

interface Props {
  line: WmsReceiveLine;
  /** Set when the session asks for the shelf's label before the product. */
  shelfState?: ShelfConfirmationState | null;
  onUndo: (line: WmsReceiveLine) => void;
  onFullReceive: (line: WmsReceiveLine) => void;
  onShortReceive: (line: WmsReceiveLine) => void;
  onSkip: (line: WmsReceiveLine) => void;
  targetLocationId?: string | null;
  targetChangePending?: boolean;
  onTargetChange?: (line: WmsReceiveLine, target: string | null) => void;
}

const STATUS_STYLES: Record<string, string> = {
  received:
    "border-success-300 bg-success-50 hover:bg-success-100 active:bg-success-100",
  short: "border-amber-300 bg-amber-50 hover:bg-amber-100 active:bg-amber-100",
  partial: "border-blue-300 bg-blue-50 hover:bg-blue-100 active:bg-blue-100",
  pending: "border-border bg-surface-card",
  skipped: "border-border bg-surface-inset opacity-50",
};

const STATUS_LABEL_KEYS: Record<string, string> = {
  received: "receiving.line.received",
  short: "receiving.line.short",
  partial: "receiving.line.partial",
  pending: "receiving.line.pending",
  skipped: "receiving.line.skipped",
};

/** The badge colours the picking row uses for the same states. */
const STATUS_VARIANTS: Record<
  string,
  "success" | "warning" | "secondary" | "danger" | "info"
> = {
  received: "success",
  short: "warning",
  partial: "info",
  pending: "secondary",
  skipped: "secondary",
};

/**
 * The word the row wears, which is not always the machine's status.
 *
 * A line part of which arrived is still ``pending`` — it is open, and its
 * actions and its place in the queue are the pending line's. The badge,
 * though, said "Pending" beside a half-full "2/4": the one word a worker
 * reads was the one word that was wrong. ``received_quantity`` is the
 * honest source, and the same read survives a reload because the server
 * serialises the quantity.
 */
function displayStatus(line: WmsReceiveLine): string {
  if (line.status === "pending" && line.received_quantity > 0) return "partial";
  return line.status;
}

/**
 * Where this line's goods are going, in the words a narrow screen can hold.
 *
 * The office page spends a full sentence on the overflow case — "Shelf A -
 * Top is full (199/200), the line lands there anyway". At 390px that wraps
 * into a paragraph and stops being scannable at arm's length, so the floor
 * splits it: the shelf on its own line, the numbers under it. Same facts,
 * two short lines instead of one long one.
 */
function PlannedShelf({ line }: { line: WmsReceiveLine }) {
  const { t } = useTranslation("warehouse");
  const planned = floorPutaway(line);
  if (!planned) return null;

  return (
    <div className="mt-1">
      <p
        className={cn(
          "text-xs font-medium",
          planned.overCapacity ? "text-amber-700" : "text-on-secondary",
        )}
      >
        {t("receiving.line.plannedAt", { location: planned.locationName })}
      </p>
      <PlannedShelfReason line={line} />
    </div>
  );
}

/** The part of a line set aside in quarantine, and why. */
export function HeldBackNote({ line }: { line: WmsReceiveLine }) {
  const { t } = useTranslation("warehouse");
  if (!(Number(line.held_quantity) > 0)) return null;
  return (
    <p className="text-xs font-medium text-amber-700">
      {t("receiving.line.heldBack", {
        qty: formatQuantityValue(line.held_quantity ?? 0),
        unit: unitLabel(t, line.uom_symbol),
        reason: line.discrepancy_code
          ? t(`detail.discrepancyCodes.${line.discrepancy_code}`)
          : "",
      })}
    </p>
  );
}

/**
 * Why the plan chose this shelf, or what is wrong with it: the lines under
 * the shelf's name. The phone's item card names the shelf in its own words
 * and puts the same reasons under it.
 */
export function PlannedShelfReason({ line }: { line: WmsReceiveLine }) {
  const { t } = useTranslation("warehouse");
  const planned = floorPutaway(line);
  if (!planned) return null;

  const rule =
    planned.source === "rule"
      ? [
          planned.ruleMatchKey
            ? t(`detail.ruleMatchKeys.${planned.ruleMatchKey}`)
            : "",
          planned.ruleMatchName,
        ]
          .filter(Boolean)
          .join(" ")
      : "";

  return (
    <>
      {planned.overCapacity && planned.shelfFill !== null && (
        <p className="text-xs text-amber-700">
          {t("receiving.line.plannedFullShared", { fill: planned.shelfFill })}
        </p>
      )}
      {planned.overCapacity && planned.shelfFill === null && (
        <p className="text-xs text-amber-700">
          {t("receiving.line.plannedFull", {
            used: planned.capacityUsed
              ? formatQuantityLocale(planned.capacityUsed)
              : "—",
            max: planned.capacityMax
              ? formatQuantityLocale(planned.capacityMax)
              : "∞",
          })}
        </p>
      )}
      {planned.warning ? (
        <p className="text-xs text-amber-700">
          {t(`receiving.line.plannedWarning.${planned.warning}`)}
        </p>
      ) : (
        rule && (
          <p className="text-xs text-on-muted">
            {t("receiving.line.plannedByRule", { rule })}
          </p>
        )
      )}
    </>
  );
}

export default function WmsReceiveLineRow({
  line,
  shelfState,
  onUndo,
  onFullReceive,
  onShortReceive,
  onSkip,
  targetLocationId,
  targetChangePending,
  onTargetChange,
}: Props) {
  const { t } = useTranslation("warehouse");
  // A skipped line is recorded like the others and is taken back the same way.
  const resolved =
    line.status === "received" ||
    line.status === "short" ||
    line.status === "skipped";
  const badgeStatus = displayStatus(line);
  // A shelf can be renamed while the goods are still in hand. Once the row
  // is resolved the decision has been acted on, and offering to change it
  // would be offering to move a pallet that is already down.
  const canPick = Boolean(onTargetChange) && line.status === "pending";

  return (
    // a plain row, not a fake button — screen readers used to
    // announce the whole row as one glued-together button even though
    // clicking it did nothing; the real actions are the buttons inside.
    //
    // One row, laid out like the picking session's: name and its context on
    // the left, the number and the status and the actions on the right, all
    // on one line. Both sessions are worked by the same person with the same
    // phone, often one after the other, and the eye had to learn the row
    // twice: the receiving one stacked four lines where picking had one and
    // put the actions under the text instead of beside it.
    <div
      className={cn(
        "flex w-full flex-wrap items-center justify-between gap-x-3 gap-y-1.5 border-b border-border px-4 py-3 text-left",
        STATUS_STYLES[badgeStatus] ?? STATUS_STYLES.pending,
      )}
    >
      <div className="min-w-0 flex-1 basis-40">
        {/* The whole name and the whole batch code, breaking at a space or
            a hyphen and inside a token only when it does not fit: both are
            read against the carton, so an ellipsis is no help. */}
        <p className="text-sm font-medium text-on [overflow-wrap:anywhere]">
          {line.product_name ?? line.document_line_id}
        </p>
        {line.lot_name && (
          <p className="text-xs text-on-muted [overflow-wrap:anywhere]">
            {line.lot_name}
          </p>
        )}
        <HeldBackNote line={line} />
        <PlannedShelf line={line} />
        {shelfState && line.status === "pending" && (
          <ShelfConfirmation state={shelfState} kind="receiving" />
        )}
        {canPick && (
          <ShelfSelect
            value={targetLocationId ?? null}
            plannedId={line.planned_location_id}
            disabled={targetChangePending}
            onChange={(target) => onTargetChange?.(line, target)}
            wrapperClassName="mt-1.5 max-w-full"
          />
        )}
      </div>

      <div className="ml-auto flex shrink-0 items-center gap-2">
        {/* Once part of the line has arrived, the count is two numbers —
            what landed and what was ordered — and the pair is how every
            other screen here says it: the scan field above and the summary
            below both read "2/5". The row used to stop at the ordered half,
            so the worker taking over an interrupted session had to undo the
            line to learn what was already counted. */}
        <span className="text-xs text-on-secondary">
          {line.received_quantity > 0
            ? `${formatQuantityValue(line.received_quantity)}/${formatQuantityValue(line.expected_quantity)}`
            : formatQuantityValue(line.expected_quantity)}{" "}
          {unitLabel(t, line.uom_symbol)}
        </span>
        {/* The same Badge the picking row carries, with the catalogue's own
            case: an uppercase 10px span was a second vocabulary for a status
            the other session already had a word for. */}
        <Badge variant={STATUS_VARIANTS[badgeStatus] ?? "secondary"}>
          {t(STATUS_LABEL_KEYS[badgeStatus] ?? "receiving.line.pending")}
        </Badge>

        {line.status === "pending" && (
          <>
            {/* The action that closes the line in full, named like the other
                two. It used to have no button of its own: a full delivery
                meant typing the expected quantity into the window that
                records the received quantity. */}
            <Button
              variant="ghost"
              size="icon"
              onClick={() => onFullReceive(line)}
              className="text-accent-600 hover:bg-accent-50 active:bg-accent-50"
              aria-label={t("receiving.line.fullReceiveAction")}
              title={t("receiving.line.fullReceiveAction")}
            >
              <CheckCircle2 size={16} />
            </Button>
            <Button
              variant="ghost"
              size="icon"
              onClick={() => onShortReceive(line)}
              className="text-amber-600 hover:bg-amber-100 active:bg-amber-100"
              aria-label={t("receiving.line.shortReceiveAction")}
              title={t("receiving.line.shortReceiveAction")}
            >
              <MinusCircle size={16} />
            </Button>
            <Button
              variant="ghost"
              size="icon"
              onClick={() => onSkip(line)}
              className="text-on-muted"
              aria-label={t("receiving.line.skipAction")}
              title={t("receiving.line.skipAction")}
            >
              <SkipForward size={16} />
            </Button>
          </>
        )}
        {resolved && (
          <Button
            variant="ghost"
            size="icon"
            onClick={() => onUndo(line)}
            className="text-on-muted"
            aria-label={t("receiving.line.undoAction")}
            title={t("receiving.line.undoAction")}
          >
            <RotateCcw size={16} />
          </Button>
        )}
      </div>
    </div>
  );
}
