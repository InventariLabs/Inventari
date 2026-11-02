import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { CheckCircle2 } from "lucide-react";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Sheet } from "@/components/ui/Sheet";
import type { WmsReceiveLine } from "@/modules/warehouse/api/documents_receiving";
import { formatQuantityValue } from "@/utils/formatters";
import { unitLabel } from "@/lib/i18nHelpers";
import { groupLinesByUnit } from "@/lib/unitQuantities";
import { SkippedLineAnswers } from "../SkippedLineAnswers";
import type { SkipOutcome } from "../SkippedLineAnswers";

interface Props {
  lines: WmsReceiveLine[];
  onClose: () => void;
  /** Called once, when the summary first appears. */
  onShown?: () => void;
  /** Takes a skip back: the line returns to the list to be received. */
  onUndoSkip?: (line: WmsReceiveLine) => void;
  /** Answers a skipped line as nothing received, under the code the person
   * chose: SHORTAGE owes the rest on a backorder, OTHER closes the gap. */
  onAnswerSkip?: (line: WmsReceiveLine, code: SkipOutcome) => void;
  /** Disables the answers while one is on its way. */
  isLoading?: boolean;
  /** What the server said when an answer was refused. */
  error?: string | null;
}

export default function WmsReceivingSummary({
  lines,
  onClose,
  onShown,
  onUndoSkip,
  onAnswerSkip,
  isLoading,
  error,
}: Props) {
  const { t } = useTranslation("warehouse");
  const [skipFault, setSkipFault] = useState<string>();
  const skipped = lines.filter((ln) => ln.status === "skipped");
  const answersSkips = onUndoSkip !== undefined && onAnswerSkip !== undefined;

  // A skipped line is put off, not short: closing the summary completes the
  // document, and it would book the line as nobody's decision.
  const close = () => {
    if (answersSkips && skipped.length > 0) {
      setSkipFault(t("receiving.summary.skippedDecide"));
      return;
    }
    onClose();
  };

  useEffect(() => {
    onShown?.();
    // Once, on appearing: the caller refreshes the document underneath.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Every line the document expected stays on the list, skipped ones
  // included: the counter above sums all expected units, so a line absent
  // from the list would be a hole in exactly the record a stockkeeper
  // files a claim from. The counter keeps one sentence per unit — pieces
  // and kilograms added together are a number in no unit at all — and a
  // line with no unit recorded counts under the generic word.
  const totals = groupLinesByUnit(lines, (ln) => ln.uom_symbol).map(
    (group) => ({
      unit: group.unit,
      received: group.lines.reduce((sum, ln) => sum + ln.received_quantity, 0),
      expected: group.lines.reduce((sum, ln) => sum + ln.expected_quantity, 0),
    }),
  );

  return (
    <Sheet
      open
      onClose={close}
      // Closing books the stock, so the only way out is the button that
      // says so: no corner X, and neither Escape nor the backdrop.
      dismissible={false}
      zIndex="modal"
      maxWidth="md"
      aria-label={t("receiving.summary.title")}
    >
      <div className="p-6">
        <div className="flex items-start justify-between">
          <div className="flex items-center gap-2">
            <CheckCircle2 size={22} className="text-success-600" />
            <h3 className="text-base font-semibold text-on">
              {t("receiving.summary.title")}
            </h3>
          </div>
        </div>

        <div className="mt-2 space-y-0.5 text-sm text-on-secondary">
          {totals.map((total) => (
            <p key={total.unit ?? ""}>
              {t("receiving.summary.total", {
                received: formatQuantityValue(total.received),
                expected: formatQuantityValue(total.expected),
                unit: total.unit
                  ? unitLabel(t, total.unit)
                  : t("common:unitsLabel", { defaultValue: "units" }),
              })}
            </p>
          ))}
        </div>

        <div className="mt-4 max-h-64 space-y-1 overflow-y-auto">
          {lines.map((ln) => (
            <div key={ln.id} className="rounded-lg bg-surface-inset px-3 py-2">
              <div className="flex items-center justify-between text-sm">
                <span className="flex min-w-0 items-center gap-2">
                  <span className="truncate font-medium text-on">
                    {ln.product_name ?? ln.document_line_id}
                  </span>
                  {ln.status === "skipped" && (
                    <Badge variant="warning">
                      {t("receiving.line.skipped")}
                    </Badge>
                  )}
                  {Number(ln.held_quantity ?? 0) > 0 && (
                    <Badge variant="warning">
                      {t("detail.heldQuantitySummary", {
                        quantity: formatQuantityValue(ln.held_quantity),
                        unit: unitLabel(t, ln.uom_symbol),
                      })}
                    </Badge>
                  )}
                </span>
                <span className="shrink-0 text-on-secondary">
                  {formatQuantityValue(ln.received_quantity)}/
                  {formatQuantityValue(ln.expected_quantity)}{" "}
                  {unitLabel(t, ln.uom_symbol)}
                </span>
              </div>
              {answersSkips && ln.status === "skipped" && (
                <div className="mt-2">
                  <SkippedLineAnswers
                    labels={{
                      undo: t("receiving.summary.skippedUndo"),
                      backorder: t("receiving.summary.skippedBackorder"),
                      notSent: t("receiving.summary.skippedNotComing"),
                    }}
                    onUndo={() => onUndoSkip(ln)}
                    onAnswer={(code) => {
                      setSkipFault(undefined);
                      onAnswerSkip(ln, code);
                    }}
                    isLoading={isLoading}
                  />
                </div>
              )}
            </div>
          ))}
        </div>

        {answersSkips && skipped.length > 0 && (
          <p className="mt-4 text-sm text-on-secondary">
            {t("receiving.summary.skippedNote")}
          </p>
        )}

        {(skipFault ?? error) && (
          <p role="alert" className="mt-2 text-sm text-on-danger">
            {skipFault ?? error}
          </p>
        )}

        {/* Stock is booked when the summary is closed, not by the last scan. */}
        <p className="mt-4 text-xs text-on-muted">
          {t("receiving.summary.bookingNote")}
        </p>

        {/* The end of the path said "Done" and led nowhere. It leads back
            to the document, which is where the received lines are. */}
        <Button onClick={close} className="mt-5 w-full">
          {t("receiving.summary.backToDocument")}
        </Button>
      </div>
    </Sheet>
  );
}
