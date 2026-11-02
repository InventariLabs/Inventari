import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import {
  CheckCircle2,
  AlertTriangle,
  PackageCheck,
  SkipForward,
} from "lucide-react";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Sheet, SheetActions, SheetFooter } from "@/components/ui/Sheet";
import type {
  WmsPickLine,
  WmsPickSession,
} from "@/modules/warehouse/api/documents";
import type { ShipmentCreate } from "@/modules/warehouse/api/shipments";
import { groupLinesByDocument } from "./documentGroups";
import { SkippedLineAnswers } from "../SkippedLineAnswers";
import type { SkipOutcome } from "../SkippedLineAnswers";
import { formatQuantityValue } from "@/utils/formatters";
import { unitLabel } from "@/lib/i18nHelpers";
import { ShipmentFields } from "../shipping/ShipmentFields";
import {
  EMPTY_SHIPMENT,
  shipmentError,
  shipmentPayload,
} from "../shipping/shipmentDraft";

interface Props {
  session: WmsPickSession;
  lines: WmsPickLine[];
  /** Whether closing completes the document, and so books the stock: the
   * sheet says so before the tap. False over several documents. */
  completesDocument?: boolean;
  /** Leaving the summary; when `completesDocument` it also completes the
   * document — with the shipment, when a dispatch names its carrier here. */
  onClose: (shipment?: ShipmentCreate) => void;
  /** Leaving the sheet by Escape or a tap outside where the button would
   * have completed the document: the dispatch stays as picked, still open
   * to be packed or looked at, and nothing is booked. */
  onLeave?: () => void;
  /** A dispatch can be packed before it is completed: leave the sheet for
   * the document's Pack step instead of completing it. Offered only for a
   * dispatch, which is also what asks for the carrier here — and shown only
   * over that one document. */
  onPack?: () => void;
  /** Takes a skip back: the line returns to the list to be picked. */
  onUndoSkip?: (line: WmsPickLine) => void;
  /** Answers a skipped line as nothing picked, under the code the person
   * chose: SHORTAGE owes the rest on a backorder, OTHER closes the gap. */
  onAnswerSkip?: (line: WmsPickLine, code: SkipOutcome) => void;
  /** Disables the answers while one is on its way. */
  isLoading?: boolean;
  /** What the server said when an answer was refused. */
  error?: string | null;
}

/** The answers a skipped line can take, and the ones it was given here. */
interface SkipAnswers {
  onUndo?: (line: WmsPickLine) => void;
  onAnswer?: (line: WmsPickLine, code: SkipOutcome) => void;
  answered: Record<string, SkipOutcome>;
  isLoading?: boolean;
}

/** Undo, Backorder and Not sent for one skipped line. */
function SkippedLine({
  line,
  answers,
}: {
  line: WmsPickLine;
  answers: SkipAnswers;
}) {
  const { t } = useTranslation("warehouse");
  const { onUndo, onAnswer, isLoading } = answers;
  return (
    <div className="ml-6 space-y-1">
      <p className="text-xs text-on-muted">
        {line.product_name} — {formatQuantityValue(line.expected_quantity)}{" "}
        {unitLabel(t, line.uom_symbol)}
      </p>
      {onUndo && onAnswer && (
        <SkippedLineAnswers
          labels={{
            undo: t("picking.skipped_undo"),
            backorder: t("picking.skipped_backorder"),
            notSent: t("picking.skipped_not_sent"),
          }}
          onUndo={() => onUndo(line)}
          onAnswer={(code) => onAnswer(line, code)}
          isLoading={isLoading}
        />
      )}
    </div>
  );
}

/** What came of a set of lines: picked, short, skipped. */
function LineBuckets({
  lines,
  answers,
}: {
  lines: WmsPickLine[];
  answers: SkipAnswers;
}) {
  const { t } = useTranslation("warehouse");
  // Spelled out so the i18n gate reads each key's call site.
  const outcome: Record<SkipOutcome, string> = {
    SHORTAGE: t("picking.skipped_backorder"),
    OTHER: t("picking.skipped_not_sent"),
  };
  const picked = lines.filter((ln) => ln.status === "picked");
  const shortPicked = lines.filter((ln) => ln.status === "short");
  const skipped = lines.filter((ln) => ln.status === "skipped");

  return (
    <>
      {picked.length > 0 && (
        <div className="rounded-xl border border-accent-200 bg-accent-50 p-3">
          <div className="flex items-center gap-2 mb-2">
            <CheckCircle2 size={16} className="text-accent-600" />
            <span className="text-sm font-medium text-accent-700">
              {t("picking.summary_picked", { count: picked.length })}
            </span>
          </div>
          {picked.map((ln) => (
            <p key={ln.id} className="text-xs text-accent-600 ml-6">
              {ln.product_name} — {formatQuantityValue(ln.picked_quantity)}{" "}
              {unitLabel(t, ln.uom_symbol)}
            </p>
          ))}
        </div>
      )}

      {shortPicked.length > 0 && (
        <div className="rounded-xl border border-amber-200 bg-amber-50 p-3">
          <div className="flex items-center gap-2 mb-2">
            <AlertTriangle size={16} className="text-amber-600" />
            <span className="text-sm font-medium text-amber-700">
              {t("picking.summary_short", { count: shortPicked.length })}
            </span>
          </div>
          {shortPicked.map((ln) => (
            <p key={ln.id} className="text-xs text-amber-600 ml-6">
              {ln.product_name} — {formatQuantityValue(ln.picked_quantity)}/
              {formatQuantityValue(ln.expected_quantity)}{" "}
              {unitLabel(t, ln.uom_symbol)}
              {answers.answered[ln.id] &&
                ` · ${outcome[answers.answered[ln.id]]}`}
            </p>
          ))}
        </div>
      )}

      {skipped.length > 0 && (
        <div className="rounded-xl border border-border bg-surface p-3">
          <div className="flex items-center gap-2 mb-2">
            <SkipForward size={16} className="text-on-muted" />
            <span className="text-sm font-medium text-on-secondary">
              {t("picking.summary_skipped", { count: skipped.length })}
            </span>
          </div>
          <div className="space-y-2">
            {skipped.map((ln) => (
              <SkippedLine key={ln.id} line={ln} answers={answers} />
            ))}
          </div>
        </div>
      )}
    </>
  );
}

export default function WmsPickingSummary({
  session,
  lines,
  completesDocument,
  onClose,
  onLeave,
  onPack,
  onUndoSkip,
  onAnswerSkip,
  isLoading,
  error,
}: Props) {
  const { t } = useTranslation("warehouse");
  const [shipment, setShipment] = useState(EMPTY_SHIPMENT);
  const [shipmentFault, setShipmentFault] = useState<string>();
  const [answered, setAnswered] = useState<Record<string, SkipOutcome>>({});
  const [skipFault, setSkipFault] = useState<string>();
  const titleRef = useRef<HTMLParagraphElement>(null);

  const skipped = lines.filter((ln) => ln.status === "skipped");
  const answersSkips = onUndoSkip !== undefined && onAnswerSkip !== undefined;
  // A skipped line is put off, not short: leaving the summary would hand
  // the document on with a line nobody has answered for.
  const skipsUnanswered = () => {
    const fault =
      answersSkips && skipped.length > 0
        ? t("picking.skipped_decide")
        : undefined;
    setSkipFault(fault);
    return fault !== undefined;
  };

  const answers: SkipAnswers = {
    onUndo: onUndoSkip,
    onAnswer:
      onAnswerSkip &&
      ((line, code) => {
        setAnswered((prev) => ({ ...prev, [line.id]: code }));
        setSkipFault(undefined);
        onAnswerSkip(line, code);
      }),
    answered,
    isLoading,
  };

  const pack = () => {
    if (!skipsUnanswered()) onPack?.();
  };

  const picked = lines.filter((ln) => ln.status === "picked");
  const groups = groupLinesByDocument(session, lines);
  // Packing and the carrier belong to one dispatch. Over several, the note
  // sends the reader to each document's own page for both; a Pack here would
  // only ever open the page the session was started from.
  const ships = Boolean(onPack) && groups.length <= 1;

  // The sheet focuses its first field — the optional carrier — and on a
  // phone a focused field raises the keyboard over the summary it opened
  // to show. The title takes the focus instead; this runs after the sheet's.
  useEffect(() => titleRef.current?.focus(), []);

  const finish = () => {
    if (skipsUnanswered()) return;
    const fault = ships ? shipmentError(shipment, t) : undefined;
    setShipmentFault(fault);
    if (!fault) onClose(ships ? shipmentPayload(shipment) : undefined);
  };
  // Spelled out so the i18n gate reads each key's call site.
  const documentStatus = {
    picking: t("picking.documents.status.picking"),
    short: t("picking.documents.status.short"),
    all_picked: t("picking.documents.status.all_picked"),
  };

  // Only the button that says it completes the document may book the
  // stock. Escape and a tap outside used to finish too, so a picker closing
  // the sheet to look at the order had shipped it unpacked, with no carrier.
  const completeLabel = completesDocument
    ? t("picking.completeAndBook")
    : t("picking.close");

  return (
    <Sheet
      open
      onClose={completesDocument ? () => onLeave?.() : finish}
      zIndex="modal"
      maxWidth="md"
      fullBleedOnMobile
      aria-label={t("picking.summary_title")}
    >
      <div className="px-4 pt-[calc(env(safe-area-inset-top)+1.25rem)] pb-5 border-b border-border shrink-0">
        <p
          ref={titleRef}
          tabIndex={-1}
          className="text-lg font-semibold text-on outline-none"
        >
          {t("picking.summary_title")}
        </p>
        <p className="text-sm text-on-secondary mt-1">
          {t("picking.summary_subtitle", {
            total: lines.length,
            picked: picked.length,
          })}
        </p>
      </div>

      <div className="flex-1 overflow-y-auto p-4 space-y-3">
        {groups.length > 1 ? (
          groups.map((group) => (
            <section
              key={group.documentId}
              aria-label={group.number}
              className="space-y-2"
            >
              <div className="flex items-center justify-between gap-2">
                <Link
                  to={`/warehouse/documents/${group.documentId}`}
                  className="text-sm font-semibold text-primary-600 hover:underline truncate"
                >
                  {group.number}
                </Link>
                <Badge
                  variant={group.status === "short" ? "warning" : "success"}
                >
                  {documentStatus[group.status]}
                </Badge>
              </div>
              <LineBuckets lines={group.lines} answers={answers} />
            </section>
          ))
        ) : (
          <LineBuckets lines={lines} answers={answers} />
        )}

        {answersSkips && skipped.length > 0 && (
          <p className="text-sm text-on-secondary">
            {t("picking.skipped_note")}
          </p>
        )}

        {(skipFault ?? error) && (
          <p role="alert" className="text-sm text-on-danger">
            {skipFault ?? error}
          </p>
        )}

        {groups.length > 1 && (
          <p className="text-sm text-on-secondary">
            {t("picking.documents.note")}
          </p>
        )}

        {completesDocument && groups.length <= 1 && (
          <p className="text-xs text-on-muted">{t("picking.bookingNote")}</p>
        )}

        {ships && (
          <ShipmentFields
            value={shipment}
            onChange={setShipment}
            error={shipmentFault}
          />
        )}
      </div>

      <SheetFooter>
        {ships ? (
          <SheetActions>
            <Button
              variant="outline"
              leftIcon={<PackageCheck size={16} />}
              onClick={pack}
            >
              {t("picking.pack")}
            </Button>
            <Button onClick={finish}>{completeLabel}</Button>
          </SheetActions>
        ) : (
          <Button onClick={finish} className="w-full">
            {completeLabel}
          </Button>
        )}
      </SheetFooter>
    </Sheet>
  );
}
