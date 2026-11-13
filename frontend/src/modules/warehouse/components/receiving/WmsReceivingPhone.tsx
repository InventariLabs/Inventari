import { useEffect, useId, useRef, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { ChevronLeft, Minus, Plus } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { QuantityInput } from "@/components/ui/QuantityInput";
import {
  Sheet,
  SheetActions,
  SheetBody,
  SheetFooter,
} from "@/components/ui/Sheet";
import { useScanResolver } from "@/hooks/useScanResolver";
import { useUomPrecisionBySymbol } from "@/hooks/useUomPrecision";
import { formatQuantityLocalized, unitLabel } from "@/lib/i18nHelpers";
import { formatQuantityValue } from "@/utils/formatters";
import type {
  WmsReceiveLine,
  WmsReceiveScanResult,
  WmsReceiveSession,
} from "@/modules/warehouse/api/documents_receiving";
import { useDocument } from "@/modules/warehouse/hooks/useDocuments";
import { floorPutaway } from "@/modules/warehouse/landedLocation";
import { ShelfSelect } from "@/modules/warehouse/components/LineTargetPicker";
import type { LocationChoice } from "@/modules/warehouse/locationChoices";
import FloorShelf, { type FloorShelfPlace } from "../FloorShelf";
import ScanField from "../ScanField";
import { shelfConfirmationState } from "../ShelfConfirmation";
import ScanRefusal from "../ScanRefusal";
import { readSessionJson, writeSessionJson } from "@/lib/localStorage";
import { buzzRefusal } from "../refusalBuzz";
import { receivingRefusal } from "./announceScanResult";
import { HeldBackNote, PlannedShelfReason } from "./WmsReceiveLineRow";

interface Props {
  documentId: string;
  session: WmsReceiveSession;
  lines: WmsReceiveLine[];
  isLoading: boolean;
  error: string | null;
  locations: LocationChoice[];
  targetChangePending: boolean;
  /** Answers whether the shelf was named. */
  onTargetChange: (
    line: WmsReceiveLine,
    target: string | null,
  ) => Promise<boolean>;
  /** One scan of the product in hand; the answer names the line it matched. */
  onScan: (barcode: string) => Promise<WmsReceiveScanResult | null | undefined>;
  /** The count on the card is what arrived of this line, in total. */
  onConfirm: (line: WmsReceiveLine, quantity: number) => Promise<void>;
  /** Close every line not yet confirmed with what arrived of it. */
  onFinishWithoutRest: () => void;
  /** Part of the count on the card is damaged or on hold: the sheet that
   *  records which part, and why, opens with the count already set. */
  onReportHeld: (line: WmsReceiveLine, quantity: number) => void;
  onComplete: () => void;
  onClose: () => void;
}

/**
 * The line the card shows: the one the worker scanned or was on, and once
 * that one is confirmed, the next open line after it. Scanning picks any
 * line; without a scan the delivery is walked in the document's order.
 */
function currentLine(
  lines: WmsReceiveLine[],
  chosenId: string | null,
): WmsReceiveLine | null {
  const chosenAt = lines.findIndex((ln) => ln.id === chosenId);
  const after = chosenAt < 0 ? lines : lines.slice(chosenAt);
  return (
    after.find((ln) => ln.status === "pending") ??
    lines.find((ln) => ln.status === "pending") ??
    null
  );
}

/** Only finite numbers come back from storage: anything else is dropped. */
function keptCounts(stored: unknown): Record<string, number> {
  if (!stored || typeof stored !== "object") return {};
  return Object.fromEntries(
    Object.entries(stored).filter(
      ([, value]) => typeof value === "number" && Number.isFinite(value),
    ),
  ) as Record<string, number>;
}

/** What the card offers before anybody touches the buttons: all of it came. */
function startingCount(line: WmsReceiveLine): number {
  return Math.max(line.expected_quantity, line.received_quantity);
}

/**
 * The figure the card counts against. A line an order asked for speaks of
 * the order; goods nobody ordered carry the count somebody wrote down, and
 * calling it ordered said something false.
 */
function expectedFigure(
  t: (key: string, options?: Record<string, unknown>) => string,
  line: WmsReceiveLine,
): string {
  const quantity = formatQuantityLocalized(
    t,
    line.expected_quantity,
    line.uom_symbol,
  );
  return line.from_order
    ? t("receiving.phone.ordered", { quantity })
    : t("receiving.phone.expected", { quantity });
}

/** The difference from the order, said under the number while it is set. */
function differenceNote(
  t: (key: string, options?: Record<string, unknown>) => string,
  line: WmsReceiveLine,
  quantity: number,
): string | null {
  const gap = line.expected_quantity - quantity;
  if (gap === 0) return null;
  // A figure somebody typed on the start card is a count, not a promise:
  // going past it is the true count, nothing to warn about.
  if (gap < 0 && line.expected_is_count) return null;
  const amount = {
    quantity: formatQuantityLocalized(t, Math.abs(gap), line.uom_symbol),
  };
  if (gap > 0) {
    return line.from_order
      ? t("receiving.phone.short", amount)
      : t("receiving.phone.shortOfExpected", amount);
  }
  return line.from_order
    ? t("receiving.phone.over", amount)
    : t("receiving.phone.overExpected", amount);
}

/**
 * Why the plan chose this location, for a plan that no rule made — a rule
 * names itself in the row's own reason line. Spelled out key by key so the
 * catalogue gate reads every one.
 */
function sourceReason(
  t: (key: string) => string,
  source: string,
): string | null {
  switch (source) {
    case "document":
      return t("receiving.phone.reason.document");
    case "line":
      return t("receiving.phone.reason.line");
    case "record":
      return t("receiving.phone.reason.record");
    case "serial":
      return t("receiving.phone.reason.serial");
    case "receiving":
      return t("receiving.phone.reason.receiving");
    default:
      return null;
  }
}

/** The count of the line in hand, with buttons a thumb can hit. */
function CountStepper({
  line,
  quantity,
  onChange,
}: {
  line: WmsReceiveLine;
  quantity: number;
  onChange: (quantity: number) => void;
}) {
  const { t } = useTranslation(["warehouse", "common"]);
  const precision = useUomPrecisionBySymbol(line.uom_symbol);
  // A tap counts one more unit: 0.001 kg per press is no button at all, and
  // a fraction is typed into the field. A unit counted in larger steps keeps
  // them.
  const step = Math.max(1, precision.step);
  const by = (direction: 1 | -1) =>
    Number(
      Math.max(0, quantity + direction * step).toFixed(precision.decimalPlaces),
    );

  return (
    <div className="flex items-center justify-center gap-3">
      <Button
        variant="outline"
        size="lg"
        aria-label={t("common:actions.decrease")}
        title={t("common:actions.decrease")}
        disabled={quantity <= 0}
        onClick={() => onChange(by(-1))}
      >
        <Minus size={20} aria-hidden="true" />
      </Button>
      <div className="flex flex-col items-center gap-1">
        <QuantityInput
          uomSymbol={line.uom_symbol}
          // Zero is an answer: nothing of this line arrived.
          min={0}
          label={t("receiving.phone.howMany", {
            name: line.product_name ?? "",
          })}
          labelClassName="sr-only"
          value={quantity}
          onQuantityChange={(next) => onChange(next ?? 0)}
          className="text-center text-lg font-semibold"
          wrapperClassName="w-28"
        />
        <span className="text-sm text-on-secondary">
          {t("receiving.phone.arrived", {
            unit: unitLabel(t, line.uom_symbol),
          })}
        </span>
      </div>
      <Button
        variant="outline"
        size="lg"
        aria-label={t("common:actions.increase")}
        title={t("common:actions.increase")}
        onClick={() => onChange(by(1))}
      >
        <Plus size={20} aria-hidden="true" />
      </Button>
    </div>
  );
}

interface CardShelf {
  id: string;
  place: FloorShelfPlace;
  reason: ReactNode;
  /** Offered by the card rather than planned: confirming the count names
   *  it as the line's shelf first, so the booking goes where the card said. */
  offered: boolean;
}

/**
 * The shelf the card names. The plan's, unless the plan is a whole zone —
 * a delivery addressed to the warehouse with no rule for its product — which
 * tells the person holding the box nothing: then the shelf the server offers
 * (where the product already lies, else the last one used there), and with
 * no offer none at all, so the card asks for one.
 */
function cardShelf(
  t: (key: string) => string,
  line: WmsReceiveLine,
  locations: LocationChoice[],
): CardShelf | null {
  const planned = floorPutaway(line);
  if (!planned || !line.planned_location_id) return null;
  const codeOf = (id: string) =>
    locations.find((loc) => loc.id === id)?.code ?? null;
  if (
    planned.source === "document" &&
    line.suggested_location_id &&
    !line.target_location_id
  ) {
    return {
      id: line.suggested_location_id,
      place: {
        code: codeOf(line.suggested_location_id),
        name: line.suggested_location_name ?? "",
      },
      reason:
        line.suggested_source === "stock"
          ? t("receiving.phone.reason.stock")
          : t("receiving.phone.reason.zone"),
      offered: true,
    };
  }
  const plannedPlace = locations.find(
    (loc) => loc.id === line.planned_location_id,
  );
  if (planned.source === "document" && plannedPlace?.leaf === false) {
    return null;
  }
  return {
    id: line.planned_location_id,
    place: {
      code: codeOf(line.planned_location_id),
      name: planned.locationName,
    },
    reason: (
      <>
        {!planned.warning && sourceReason(t, planned.source) && (
          <p>{sourceReason(t, planned.source)}</p>
        )}
        <PlannedShelfReason line={line} />
      </>
    ),
    offered: false,
  };
}

/**
 * Where the goods of this line go, and the way to put them somewhere else:
 * a location picked from the list or scanned off its label.
 */
function PutawayBlock({
  line,
  shelf,
  session,
  pending,
  elsewhere,
  onElsewhere,
  onTargetChange,
}: {
  line: WmsReceiveLine;
  shelf: CardShelf | null;
  session: WmsReceiveSession;
  pending: boolean;
  /** Whether the worker is naming another location for this line. */
  elsewhere: boolean;
  onElsewhere: (open: boolean) => void;
  onTargetChange: (line: WmsReceiveLine, target: string | null) => void;
}) {
  const { t } = useTranslation(["warehouse", "common"]);
  const { resolve } = useScanResolver({
    handle: (result) => {
      if (result.action === "set_storage_context" && result.location) {
        onTargetChange(line, result.location.id);
        onElsewhere(false);
      } else {
        toast.error(t("receiving.phone.notALocation"));
      }
      // Anything else scanned here is answered here: the offer to open it
      // on another screen would walk away from the delivery.
      return true;
    },
    acceptUnrecognized: () => {
      toast.error(t("receiving.phone.notALocation"));
      return true;
    },
  });

  return (
    <div className="space-y-2">
      {(shelf || !elsewhere) && (
        <FloorShelf
          label={t("receiving.phone.putOn")}
          shelf={shelf?.place ?? null}
          reason={shelf?.reason}
          confirmation={
            // Asked for only where the planned shelf has something to scan,
            // as the session asks: a codeless place is taken on the
            // worker's word.
            shelf && !shelf.offered && line.planned_location_code
              ? shelfConfirmationState(session, shelf.id)
              : null
          }
          kind="receiving"
          onChoose={() => onElsewhere(true)}
        />
      )}
      {elsewhere ? (
        <div className="space-y-2">
          <p className="text-sm text-on-secondary">
            {t("receiving.phone.elsewhereHint")}
          </p>
          <ShelfSelect
            value={line.target_location_id ?? null}
            plannedId={line.planned_location_id}
            disabled={pending}
            placeholder={t("floorShelf.choose")}
            onChange={(target) => {
              onTargetChange(line, target);
              onElsewhere(false);
            }}
          />
          <ScanField
            prompt={t("receiving.phone.scanLocation")}
            disabled={pending}
            onCode={(code) => void resolve(code)}
          />
          <Button
            variant="ghost"
            className="w-full"
            onClick={() => onElsewhere(false)}
          >
            {t("common:form.cancel")}
          </Button>
        </div>
      ) : (
        shelf && (
          <Button
            variant="ghost"
            className="w-full"
            onClick={() => onElsewhere(true)}
          >
            {t("receiving.phone.elsewhere")}
          </Button>
        )
      )}
    </div>
  );
}

/**
 * Receiving a delivery on a phone, one item at a time: scan the product (or
 * take the next one), set how many arrived with big buttons, see where it
 * goes, confirm. Every confirmation is saved on the session at once, so a
 * closed app opens again on the item it left. When the rest of the delivery
 * did not come, one button closes what is left; the missing quantities stay
 * expected on the order.
 */
export default function WmsReceivingPhone({
  documentId,
  session,
  lines,
  isLoading,
  error,
  locations,
  targetChangePending,
  onTargetChange,
  onScan,
  onConfirm,
  onFinishWithoutRest,
  onReportHeld,
  onComplete,
  onClose,
}: Props) {
  const { t } = useTranslation(["warehouse", "common"]);
  const { data: document } = useDocument(documentId);
  const headingId = useId();
  const [chosenId, setChosenId] = useState<string | null>(null);
  const [scannedId, setScannedId] = useState<string | null>(null);
  // The count set on each card, kept while the worker scans another item
  // and comes back to this one — and, in this tab, across Back and resume:
  // the header says the sheet saves as it goes, and a count typed but not
  // yet confirmed lives nowhere else.
  const countsKey = `wms-receiving-counts:${session.id}`;
  const [counts, setCounts] = useState<Record<string, number>>(() =>
    keptCounts(readSessionJson<unknown>(countsKey, {})),
  );
  useEffect(() => {
    writeSessionJson(countsKey, counts);
  }, [countsKey, counts]);
  const [askRest, setAskRest] = useState(false);
  // The line whose location is being named. While it is, a scan is a
  // location label, and the product scan steps aside: two fields listening
  // to one hardware scanner would both act on the same code.
  const [elsewhereFor, setElsewhereFor] = useState<string | null>(null);
  // Scans wait here in the order they were read and go to the server one at
  // a time: a scanner does not wait for the screen, and a code read while the
  // last one is still out is neither dropped nor answered out of order.
  const scanQueue = useRef<Promise<void>>(Promise.resolve());
  const latest = useRef({ lines, onScan });
  latest.current = { lines, onScan };
  // The codes the server did not record, until they are read again.
  const [unrecorded, setUnrecorded] = useState<string[]>([]);
  // What the last refused scan said, until the next scan answers.
  const [refusal, setRefusal] = useState<string | null>(null);

  const line = currentLine(lines, chosenId);
  const open = lines.filter((ln) => ln.status === "pending");
  const heldLines = lines.filter(
    (ln) => ln.status !== "pending" && Number(ln.held_quantity) > 0,
  );
  const done = lines.length - open.length;
  const percent = lines.length ? Math.round((done / lines.length) * 100) : 0;
  const quantity = line ? (counts[line.id] ?? startingCount(line)) : 0;
  const isLast = open.length === 1;
  const partner = document?.partner_snapshot?.name;
  const title = partner
    ? t("receiving.phone.title", { partner })
    : t("receiving.title");

  const scanProduct = (code: string) => {
    scanQueue.current = scanQueue.current.then(async () => {
      // A scan that throws is one the server did not record, and must not
      // leave the queue rejected for every scan after it.
      const result = await latest.current.onScan(code).catch(() => null);
      setUnrecorded((prev) => {
        const rest = prev.filter((other) => other !== code);
        return result ? rest : [...rest, code];
      });
      const refused = receivingRefusal(t, result);
      setRefusal(refused);
      if (refused) buzzRefusal();
      if (
        result?.line_id &&
        latest.current.lines.some((ln) => ln.id === result.line_id)
      ) {
        setChosenId(result.line_id);
        setScannedId(result.line_id);
      }
    });
  };

  // What was read before the worker pressed Back is sent first.
  const leave = () => {
    void scanQueue.current.then(onClose);
  };

  const shelf = line ? cardShelf(t, line, locations) : null;

  const confirm = async () => {
    if (!line) return;
    setChosenId(line.id);
    if (shelf?.offered && !(await onTargetChange(line, shelf.id))) return;
    await onConfirm(line, quantity);
  };

  const note = line ? differenceNote(t, line, quantity) : null;

  return (
    <Sheet
      open
      onClose={leave}
      zIndex="modal"
      maxWidth="md"
      fullBleedOnMobile
      aria-labelledby={headingId}
    >
      <div className="shrink-0 space-y-2 border-b border-border bg-surface-card px-2 pt-[calc(env(safe-area-inset-top)+0.5rem)] pb-3">
        <div className="flex items-center justify-between gap-2">
          <Button
            variant="ghost"
            leftIcon={<ChevronLeft size={16} aria-hidden="true" />}
            onClick={leave}
          >
            {t("receiving.phone.back")}
          </Button>
          <span className="px-2 text-sm text-on-secondary">
            {t("receiving.phone.savesAsYouGo")}
          </span>
        </div>
        <div className="space-y-1.5 px-2">
          <h2 id={headingId} className="text-lg font-semibold text-on">
            {title}
          </h2>
          <div className="flex items-center gap-3">
            <div
              role="progressbar"
              aria-valuemin={0}
              aria-valuemax={100}
              aria-valuenow={percent}
              aria-label={t("receiving.phone.progress", {
                count: done,
                total: lines.length,
              })}
              className="h-1.5 flex-1 overflow-hidden rounded-full bg-surface-raised"
            >
              <div
                className="h-full rounded-full bg-primary-600"
                style={{ width: `${percent}%` }}
              />
            </div>
            <span className="text-sm text-on-secondary tabular-nums">
              {t("receiving.phone.progress", {
                count: done,
                total: lines.length,
              })}
            </span>
          </div>
        </div>
      </div>

      <SheetBody className="space-y-4 bg-surface p-4">
        {error && (
          <p
            role="alert"
            className="rounded-lg bg-red-50 px-3 py-2 text-sm text-on-danger"
          >
            {error}
          </p>
        )}

        {line ? (
          <>
            {elsewhereFor !== line.id && (
              <ScanField
                prompt={t("receiving.phone.scanPrompt")}
                onCode={scanProduct}
              />
            )}
            {refusal && <ScanRefusal message={refusal} />}
            {unrecorded.length > 0 && (
              <p
                role="alert"
                className="rounded-lg bg-red-50 px-3 py-2 text-sm text-on-danger"
              >
                {t("receiving.phone.scansNotRecorded", {
                  codes: unrecorded.join(", "),
                })}
              </p>
            )}
            <Card
              role="region"
              aria-label={line.product_name ?? undefined}
              className="space-y-4 p-4"
            >
              <div className="space-y-0.5">
                {scannedId === line.id && (
                  <p className="text-xs font-medium text-on-success">
                    {t("receiving.phone.scanned")}
                  </p>
                )}
                <h3 className="text-xl font-semibold text-on">
                  {line.product_name}
                </h3>
                <p className="text-sm text-on-secondary">
                  {expectedFigure(t, line)}
                  {line.received_quantity > 0 &&
                    ` · ${t("receiving.phone.countedSoFar", {
                      quantity: formatQuantityLocalized(
                        t,
                        line.received_quantity,
                        line.uom_symbol,
                      ),
                    })}`}
                </p>
              </div>
              <CountStepper
                line={line}
                quantity={quantity}
                onChange={(next) =>
                  setCounts((prev) => ({ ...prev, [line.id]: next }))
                }
              />
              {note && <p className="text-sm text-on-warning">{note}</p>}
              <Button
                variant="ghost"
                className="w-full"
                disabled={isLoading}
                onClick={() => onReportHeld(line, quantity)}
              >
                {t("receiving.phone.heldPart")}
              </Button>
              <PutawayBlock
                line={line}
                shelf={shelf}
                session={session}
                pending={targetChangePending}
                elsewhere={elsewhereFor === line.id}
                onElsewhere={(open) => setElsewhereFor(open ? line.id : null)}
                onTargetChange={(ln, target) => void onTargetChange(ln, target)}
              />
            </Card>
            <Button
              variant="outline"
              size="lg"
              className="w-full"
              disabled={isLoading}
              onClick={() => setAskRest(true)}
            >
              {t("receiving.phone.rest")}
            </Button>
          </>
        ) : (
          <p className="text-sm text-on-secondary">
            {t("receiving.phone.allCounted")}
          </p>
        )}
        {/* A line leaves the card once it is counted, and with it the part
            of it that went to quarantine: said here, so the worker sees
            what was set aside and why without opening anything. */}
        {heldLines.length > 0 && (
          <ul className="space-y-1">
            {heldLines.map((ln) => (
              <li key={ln.id}>
                <p className="flex justify-between gap-x-3 text-sm font-medium text-on">
                  <span className="min-w-0 truncate">{ln.product_name}</span>
                  <span className="shrink-0 text-xs text-on-secondary">
                    {formatQuantityValue(ln.received_quantity)}/
                    {formatQuantityValue(ln.expected_quantity)}{" "}
                    {unitLabel(t, ln.uom_symbol)}
                  </span>
                </p>
                <HeldBackNote line={ln} />
              </li>
            ))}
          </ul>
        )}
      </SheetBody>

      <SheetFooter>
        <SheetActions>
          {line ? (
            <Button
              size="lg"
              isLoading={isLoading}
              onClick={() => void confirm()}
            >
              {isLast ? t("receiving.phone.finish") : t("receiving.phone.next")}
            </Button>
          ) : (
            <Button size="lg" isLoading={isLoading} onClick={onComplete}>
              {t("receiving.complete")}
            </Button>
          )}
        </SheetActions>
      </SheetFooter>

      <ConfirmDialog
        open={askRest}
        title={t("receiving.phone.restTitle")}
        message={t("receiving.phone.restMessage", { count: open.length })}
        confirmLabel={t("receiving.phone.restConfirm")}
        cancelLabel={t("receiving.phone.restKeep")}
        onConfirm={() => {
          setAskRest(false);
          onFinishWithoutRest();
        }}
        onCancel={() => setAskRest(false)}
      />
    </Sheet>
  );
}
