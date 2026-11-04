import { Package } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Badge } from "@/components/ui/Badge";
import { Card } from "@/components/ui/Card";
import { useDocumentCurrency } from "@/hooks/useDocumentCurrency";
import { DocumentLineExtra } from "@/modules/warehouse/components/DocumentLineExtra";
import { DocumentDetailLineCards } from "@/modules/warehouse/components/DocumentDetailLineCards";
import { landedElsewhere } from "@/modules/warehouse/landedLocation";
import { LineTargetPicker } from "@/modules/warehouse/components/LineTargetPicker";
import { PlannedPutawayLine } from "./PlannedPutawayLine";
import {
  documentHasExecution,
  getDocumentLineStatus,
  getDocumentLineStatusVariant,
} from "@/modules/warehouse/lineStatus";
import { unitLabel } from "@/lib/i18nHelpers";
import { useShowDocumentValue } from "@/modules/warehouse/hooks/useShowDocumentValue";
import type { WarehouseDocument } from "@/modules/warehouse/types";
import { CorrectionDirection, CorrectionQuantity } from "./CorrectionQuantity";
import { formatDecimalQty, formatMoney } from "@/utils/formatters";

interface DocumentDetailLinesCardProps {
  document: WarehouseDocument;
  formatQuantity: (value: number) => string;
  targetChangePending?: boolean;
  onLineTargetChange?: (lineId: string, target: string | null) => void;
}

const isCorrection = (doc: WarehouseDocument) => doc.type === "CORRECTION";

export function DocumentDetailLinesCard({
  document,
  formatQuantity,
  targetChangePending,
  onLineTargetChange,
}: DocumentDetailLinesCardProps) {
  const { t, i18n } = useTranslation("warehouse");
  const currency = useDocumentCurrency(document.currency);
  // Price and gross columns belong to the documents that carry a value —
  // receipts and issues — and only while the profile tracks it. A stored
  // value on a transfer is still stored and registered; this card just
  // does not print it.
  const showValue = useShowDocumentValue(document.type);

  const hasValueColumns =
    showValue && document.lines.some((l) => l.unit_price != null);

  return (
    <Card className="overflow-hidden">
      <div className="flex items-center justify-between px-4 sm:px-6 py-3 border-b border-border">
        {/* First level of content under the page title (UI_GUIDELINES §2.11). */}
        <h2 className="font-medium text-on text-sm">
          {t("fields.lines")}
          <span className="ml-2 text-xs text-on-muted font-normal">
            {t("detail.linesCount", { count: document.lines.length })}
          </span>
        </h2>
      </div>

      {document.lines.length === 0 ? (
        <div className="flex flex-col items-center py-10 gap-2">
          <Package size={28} className="text-on-muted" />
          <p className="text-sm text-on-secondary">{t("detail.noLines")}</p>
        </div>
      ) : (
        <>
          <DocumentDetailLineCards
            document={document}
            formatQuantity={formatQuantity}
            targetChangePending={targetChangePending}
            onLineTargetChange={onLineTargetChange}
          />
          {/* From `sm` up the same lines are a real table (UI_GUIDELINES §14.1).
              Below it they would need more width than the screen has, and the
 first column to fall off the edge was the line status. */}
          <div className="hidden sm:block overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left border-b border-border bg-surface-raised/50">
                  <th
                    scope="col"
                    className="px-4 py-2.5 text-xs font-medium text-on-muted w-8"
                  >
                    {t("detail.lineNumber")}
                  </th>
                  <th
                    scope="col"
                    className="px-4 py-2.5 text-xs font-medium text-on-muted"
                  >
                    {t("lines.item")}
                  </th>
                  <th
                    scope="col"
                    className="px-4 py-2.5 text-xs font-medium text-on-muted text-right"
                  >
                    {t("lines.quantity")}
                  </th>
                  <th
                    scope="col"
                    className="px-4 py-2.5 text-xs font-medium text-on-muted"
                  >
                    {t("lines.unit")}
                  </th>
                  {hasValueColumns && (
                    <>
                      <th
                        scope="col"
                        className="px-4 py-2.5 text-xs font-medium text-on-muted text-right hidden sm:table-cell"
                      >
                        {t("lines.unitPrice")}
                      </th>
                      <th
                        scope="col"
                        className="px-4 py-2.5 text-xs font-medium text-on-muted text-right hidden sm:table-cell"
                      >
                        {t("lines.lineGross")}
                      </th>
                    </>
                  )}
                  {!isCorrection(document) && (
                    <th
                      scope="col"
                      className="px-4 py-2.5 text-xs font-medium text-on-muted"
                    >
                      {t("detail.lineStatus")}
                    </th>
                  )}
                  <th
                    scope="col"
                    className="px-4 py-2.5 text-xs font-medium text-on-muted hidden sm:table-cell"
                  >
                    {t("lines.batchNumber")}
                  </th>
                  <th
                    scope="col"
                    className="px-4 py-2.5 text-xs font-medium text-on-muted hidden sm:table-cell"
                  >
                    {t("lines.expiryDate")}
                  </th>
                </tr>
              </thead>
              <tbody>
                {document.lines.map((line) => {
                  // Quantities ride the wire as decimal strings, so the raw
                  // fields become numbers once, here — everything below
                  // compares or formats them.
                  const expectedQuantity = Number(
                    line.expected_quantity ?? line.quantity,
                  );
                  const doneQuantity = Number(
                    line.done_quantity ??
                      (document.status === "DRAFT" ||
                      document.status === "CANCELLED"
                        ? 0
                        : expectedQuantity),
                  );
                  const lineStatus = getDocumentLineStatus(
                    line,
                    document.status,
                  );
                  // Once any line has moved, a line whose done quantity is not
                  // its plan — short, unmoved or over-received — prints what
                  // came in as its number and the plan beside it: the planned
                  // number alone reads as arrived, and a surplus never shows
                  // the quantity that entered stock. The quantities ride the
                  // wire as decimal strings, so the comparison is numeric:
                  // "3.000" < "10.000" is false lexicographically.
                  const owesExecutionSummary =
                    documentHasExecution(document) &&
                    doneQuantity !== expectedQuantity;
                  const discrepancyLabel = line.discrepancy_code
                    ? t(`detail.discrepancyCodes.${line.discrepancy_code}`)
                    : null;

                  return (
                    <tr
                      key={line.id}
                      className="border-b border-border last:border-b-0 hover:bg-surface-raised/30 transition-colors"
                    >
                      <td className="px-4 py-3 text-on-muted text-xs">
                        {line.line_number}
                      </td>
                      <td className="px-4 py-3">
                        <LineNameCell
                          document={document}
                          line={line}
                          discrepancyLabel={discrepancyLabel}
                          targetChangePending={targetChangePending}
                          onLineTargetChange={onLineTargetChange}
                        />
                      </td>
                      <td className="px-4 py-3 text-right font-mono text-on">
                        {isCorrection(document) ? (
                          <div className="flex flex-col items-end">
                            <CorrectionQuantity
                              document={document}
                              difference={expectedQuantity}
                              formatQuantity={formatQuantity}
                            />
                            <CorrectionDirection
                              document={document}
                              difference={expectedQuantity}
                            />
                          </div>
                        ) : (
                          <div className="flex flex-col items-end">
                            <div className="font-semibold">
                              {formatQuantity(
                                owesExecutionSummary
                                  ? doneQuantity
                                  : expectedQuantity,
                              )}
                            </div>
                            {/* The received number printed, not parked
                                      in a tooltip: it was invisible on touch,
                                      in print and in copied text. `font-sans`:
                                      the cell is mono and the sentence is
                                      prose. */}
                            {owesExecutionSummary && (
                              <span className="font-sans text-xs text-on-secondary">
                                {t("detail.executionSummary", {
                                  done: formatQuantity(doneQuantity),
                                  expected: formatQuantity(expectedQuantity),
                                })}
                              </span>
                            )}
                            {/* Only while execution is genuinely part-done. An
                              empty track under every number in a read-only
                              table reads as an underlined input field, and a
                              full one says nothing the status badge does not.
                              The bar is also a meter, so it says so. */}
                            {doneQuantity > 0 &&
                              doneQuantity < expectedQuantity && (
                                <div
                                  role="meter"
                                  aria-valuemin={0}
                                  aria-valuemax={expectedQuantity}
                                  aria-valuenow={doneQuantity}
                                  aria-label={t("detail.executionSummary", {
                                    done: formatQuantity(doneQuantity),
                                    expected: formatQuantity(expectedQuantity),
                                  })}
                                  className="mt-1.5 h-1 w-12 bg-surface-inset rounded-full overflow-hidden"
                                >
                                  <div
                                    className="h-full bg-accent-500 transition-all duration-500"
                                    style={{
                                      width: `${Math.min(100, (doneQuantity / expectedQuantity) * 100)}%`,
                                    }}
                                  />
                                </div>
                              )}
                          </div>
                        )}
                      </td>
                      <td className="px-4 py-3 text-on-secondary">
                        {unitLabel(t, line.uom?.symbol ?? "")}
                      </td>
                      {hasValueColumns && (
                        <>
                          <td className="px-4 py-3 text-right font-mono text-on hidden sm:table-cell">
                            {formatMoney(
                              line.unit_price,
                              currency,
                              i18n.language,
                            )}
                          </td>
                          <td className="px-4 py-3 text-right font-mono font-medium text-on hidden sm:table-cell">
                            {formatMoney(
                              line.line_gross,
                              currency,
                              i18n.language,
                            )}
                          </td>
                        </>
                      )}
                      {!isCorrection(document) && (
                        <td className="px-4 py-3">
                          <Badge
                            variant={getDocumentLineStatusVariant(lineStatus)}
                          >
                            {t(`detail.lineStatuses.${lineStatus}`)}
                          </Badge>
                        </td>
                      )}
                      <td className="px-4 py-3 text-on-secondary hidden sm:table-cell">
                        {line.batch_number ?? "—"}
                      </td>
                      <td className="px-4 py-3 text-on-secondary hidden sm:table-cell">
                        {line.expiry_date ?? "—"}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </>
      )}
    </Card>
  );
}

interface LineNameCellProps {
  document: WarehouseDocument;
  line: WarehouseDocument["lines"][number];
  discrepancyLabel: string | null;
  targetChangePending?: boolean;
  onLineTargetChange?: (lineId: string, target: string | null) => void;
}

/**
 * The item column of a table row: the name and every sentence the line has
 * to say about itself — where it will land, the shelf the worker named,
 * where it did land, the shelf it takes from, notes, and the recorded
 * discrepancy. Its own component
 * because together those branches outgrew the row's render function.
 */
function LineNameCell({
  document,
  line,
  discrepancyLabel,
  targetChangePending,
  onLineTargetChange,
}: LineNameCellProps) {
  const { t } = useTranslation("warehouse");
  return (
    <>
      <div className="font-medium text-on">{line.name ?? "—"}</div>
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
        <div className="mt-1 text-xs text-on-secondary">
          {t("detail.landedElsewhere", {
            location: landedElsewhere(document, line),
          })}
        </div>
      )}
      {line.source_location_name && (
        <div className="mt-1 text-xs text-on-secondary">
          {t("detail.takenFrom", { location: line.source_location_name })}
        </div>
      )}
      {line.notes && (
        <div className="mt-1 text-xs text-on-secondary whitespace-pre-wrap">
          {line.notes}
        </div>
      )}
      {(discrepancyLabel || line.discrepancy_reason) && (
        <div className="mt-1 text-xs text-amber-700 whitespace-pre-wrap">
          {line.discrepancy_reason
            ? t("detail.discrepancySummaryWithNote", {
                code: discrepancyLabel,
                reason: line.discrepancy_reason,
              })
            : t("detail.discrepancySummaryCodeOnly", {
                code: discrepancyLabel,
              })}
        </div>
      )}
      {Number(line.held_quantity ?? 0) > 0 && (
        <div className="mt-1 text-xs text-amber-700">
          {t("detail.heldQuantitySummary", {
            quantity: formatDecimalQty(line.held_quantity),
            unit: unitLabel(t, line.uom?.symbol ?? ""),
          })}
        </div>
      )}
      <DocumentLineExtra document={document} line={line} />
    </>
  );
}
