import { DocumentLineExtra } from "@/modules/warehouse/components/DocumentLineExtra";
import { useTranslation } from "react-i18next";
import { Badge } from "@/components/ui/Badge";
import { useDocumentCurrency } from "@/hooks/useDocumentCurrency";
import {
  documentHasExecution,
  getDocumentLineStatus,
  getDocumentLineStatusVariant,
} from "@/modules/warehouse/lineStatus";
import { landedElsewhere } from "@/modules/warehouse/landedLocation";
import { LineTargetPicker } from "@/modules/warehouse/components/LineTargetPicker";
import { PlannedPutawayLine } from "./PlannedPutawayLine";
import { unitLabel } from "@/lib/i18nHelpers";
import { useShowDocumentValue } from "@/modules/warehouse/hooks/useShowDocumentValue";
import type { WarehouseDocument } from "@/modules/warehouse/types";
import { CorrectionDirection, CorrectionQuantity } from "./CorrectionQuantity";
import { formatDecimalQty, formatMoney } from "@/utils/formatters";

interface DocumentDetailLineCardsProps {
  document: WarehouseDocument;
  formatQuantity: (value: number) => string;
  targetChangePending?: boolean;
  onLineTargetChange?: (lineId: string, target: string | null) => void;
}

/**
 * The document's lines on a phone.
 *
 * The table this replaces below `sm` needed more width than a 390px screen has:
 * it scrolled sideways, and the column it cut first was the line status — the
 * one thing a warehouse worker opens the document to check. A card per
 * line puts the status next to the item name and stacks the rest underneath.
 *
 * A separate render branch for phones is the sanctioned pattern
 * (UI_GUIDELINES §14.1); the desktop list stays a real `<table>`.
 */
export function DocumentDetailLineCards({
  document,
  formatQuantity,
  targetChangePending,
  onLineTargetChange,
}: DocumentDetailLineCardsProps) {
  const currency = useDocumentCurrency(document.currency);

  return (
    <ul className="sm:hidden divide-y divide-border">
      {document.lines.map((line) => (
        <LineCard
          key={line.id}
          document={document}
          line={line}
          formatQuantity={formatQuantity}
          currency={currency}
          targetChangePending={targetChangePending}
          onLineTargetChange={onLineTargetChange}
        />
      ))}
    </ul>
  );
}

interface LineCardProps {
  document: WarehouseDocument;
  line: WarehouseDocument["lines"][number];
  formatQuantity: (value: number) => string;
  currency: string | undefined;
  targetChangePending?: boolean;
  onLineTargetChange?: (lineId: string, target: string | null) => void;
}

function LineCard({
  document,
  line,
  formatQuantity,
  currency,
  targetChangePending,
  onLineTargetChange,
}: LineCardProps) {
  const { t } = useTranslation("warehouse");
  const isCorrection = document.type === "CORRECTION";
  // Price and gross belong to the documents that carry a value, and only
  // while the profile tracks it.
  const showValue = useShowDocumentValue(document.type);

  // Quantities ride the wire as decimal strings, so the raw fields become
  // numbers once, here — everything below compares or formats them.
  const expectedQuantity = Number(line.expected_quantity ?? line.quantity);
  const doneQuantity = Number(
    line.done_quantity ??
      (document.status === "DRAFT" || document.status === "CANCELLED"
        ? 0
        : expectedQuantity),
  );
  const lineStatus = getDocumentLineStatus(line, document.status);
  // The table prints a dash in an empty Unit cell to keep the column
  // aligned; a card has no column to hold open, so an unknown unit is
  // simply left out.
  const unit = line.uom?.symbol ? unitLabel(t, line.uom.symbol) : null;
  // Once any line has moved, a line whose done quantity is not its plan —
  // short, unmoved or over-received — prints what came in as its number and
  // the plan beside it: the planned number alone reads as arrived, and a
  // surplus never shows the quantity that entered stock. The quantities ride
  // the wire as decimal strings, so the comparison is numeric: "3.000" <
  // "10.000" is false lexicographically.
  const owesExecutionSummary =
    documentHasExecution(document) && doneQuantity !== expectedQuantity;

  return (
    <li className="px-4 py-3 space-y-1.5">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <span className="text-xs text-on-muted">{line.line_number}</span>
          <span className="ml-2 font-medium text-on break-words">
            {line.name ?? "—"}
          </span>
        </div>
        {!isCorrection && (
          <Badge
            variant={getDocumentLineStatusVariant(lineStatus)}
            className="shrink-0"
          >
            {t(`detail.lineStatuses.${lineStatus}`)}
          </Badge>
        )}
      </div>

      <div className="flex items-baseline gap-2 font-mono text-sm">
        {isCorrection ? (
          <CorrectionQuantity
            document={document}
            difference={expectedQuantity}
            formatQuantity={formatQuantity}
          />
        ) : (
          <span className="font-semibold text-on">
            {formatQuantity(
              owesExecutionSummary ? doneQuantity : expectedQuantity,
            )}
          </span>
        )}
        {unit && <span className="text-on-secondary">{unit}</span>}
        {isCorrection && (
          <CorrectionDirection
            document={document}
            difference={expectedQuantity}
          />
        )}
        {owesExecutionSummary && (
          <span className="font-sans text-xs text-on-secondary">
            {t("detail.executionSummary", {
              done: formatQuantity(doneQuantity),
              expected: formatQuantity(expectedQuantity),
            })}
          </span>
        )}
      </div>

      <PlannedPutawayLine line={line} />

      {onLineTargetChange && (
        <LineTargetPicker
          document={document}
          line={line}
          disabled={targetChangePending}
          onChange={onLineTargetChange}
        />
      )}

      {landedElsewhere(document, line) && (
        <p className="text-xs text-on-secondary">
          {t("detail.landedElsewhere", {
            location: landedElsewhere(document, line),
          })}
        </p>
      )}

      {line.source_location_name && (
        <p className="text-xs text-on-secondary">
          {t("detail.takenFrom", { location: line.source_location_name })}
        </p>
      )}

      <LineCardDetails line={line} currency={currency} showValue={showValue} />
      <DocumentLineExtra document={document} line={line} />
    </li>
  );
}

/**
 * Everything under the quantity line: value, lot and expiry, notes, and the
 * discrepancy the receiver recorded. Its own component because each of those
 * is conditional, and together they carry more branches than one function is
 * allowed to hold.
 */
function LineCardDetails({
  line,
  currency,
  showValue,
}: Pick<LineCardProps, "line" | "currency"> & { showValue: boolean }) {
  const { t, i18n } = useTranslation("warehouse");
  const discrepancyLabel = line.discrepancy_code
    ? t(`detail.discrepancyCodes.${line.discrepancy_code}`)
    : null;
  const lotAndExpiry = [
    line.batch_number && `${t("lines.batchNumber")}: ${line.batch_number}`,
    line.expiry_date && `${t("lines.expiryDate")}: ${line.expiry_date}`,
  ].filter(Boolean);

  return (
    <>
      {showValue && line.unit_price != null && (
        <p className="text-xs text-on-secondary">
          {formatMoney(line.unit_price, currency, i18n.language)}
          {line.line_gross != null && (
            <>
              {" · "}
              <span className="text-on">
                {formatMoney(line.line_gross, currency, i18n.language)}
              </span>
            </>
          )}
        </p>
      )}

      {lotAndExpiry.length > 0 && (
        <p className="text-xs text-on-secondary">{lotAndExpiry.join(" · ")}</p>
      )}

      {line.notes && (
        <p className="text-xs text-on-secondary whitespace-pre-wrap">
          {line.notes}
        </p>
      )}

      {(discrepancyLabel || line.discrepancy_reason) && (
        <p className="text-xs text-amber-700 whitespace-pre-wrap">
          {line.discrepancy_reason
            ? t("detail.discrepancySummaryWithNote", {
                code: discrepancyLabel,
                reason: line.discrepancy_reason,
              })
            : t("detail.discrepancySummaryCodeOnly", {
                code: discrepancyLabel,
              })}
        </p>
      )}
      {Number(line.held_quantity ?? 0) > 0 && (
        <p className="text-xs text-amber-700">
          {t("detail.heldQuantitySummary", {
            quantity: formatDecimalQty(line.held_quantity),
            unit: unitLabel(t, line.uom?.symbol ?? ""),
          })}
        </p>
      )}
    </>
  );
}
