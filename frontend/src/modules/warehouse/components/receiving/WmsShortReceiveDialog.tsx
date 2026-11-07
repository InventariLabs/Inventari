import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Loader2 } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Checkbox } from "@/components/ui/Checkbox";
import { NativeSelect } from "@/components/ui/NativeSelect";
import { Sheet, SheetActions, SheetBody } from "@/components/ui/Sheet";
import { Input } from "@/components/ui/Input";
import { QuantityInput } from "@/components/ui/QuantityInput";
import {
  DOCUMENT_DISCREPANCY_CODES,
  DOCUMENT_HELD_CODES,
} from "@/modules/warehouse/discrepancyCodes";
import type { WmsReceiveLine } from "@/modules/warehouse/api/documents_receiving";
import { formatQuantityLocalized } from "@/lib/i18nHelpers";

/** The two codes that can hold received goods back, not only explain a gap. */
function isHeldCode(code: string): boolean {
  return code === "DAMAGE" || code === "QUALITY_HOLD";
}

/** A typed held quantity is an answer when it is a number at or above zero;
 *  "all of it" needs no number of its own. */
function isValidHeldAnswer(heldAll: boolean, held: number): boolean {
  return heldAll || (Number.isFinite(held) && held >= 0);
}

/** Damage and Quality hold mean two things: on a short line with nothing
 *  held back they explain only the gap. */
function explainsAGapOnly(
  showsDiscrepancy: boolean,
  holds: boolean,
  code: string,
): boolean {
  return showsDiscrepancy && !holds && isHeldCode(code);
}

/** The total the sheet opens on: the count somebody already set, else the scans. */
function startingTotal(initial: number | undefined, scanned: number): number {
  return initial ?? scanned;
}

interface Props {
  line: WmsReceiveLine;
  /** The total to start from when somebody has already counted it, in place
   *  of the quantity the scans recorded. */
  initialQuantity?: number;
  isLoading: boolean;
  /** Server-side error for the receiving session — rendered inside
   * this dialog so it is not hidden behind the active view. */
  serverError?: string | null;
  onConfirm: (
    lineId: string,
    receivedQty: number,
    code: string,
    reason?: string,
    replaceScans?: boolean,
    heldQty?: number,
  ) => void;
  onCancel: () => void;
  /** Out of sight while another question sits on the same layer. The sheet
   *  stays mounted, so what was typed in it is still there when it returns. */
  hidden?: boolean;
}

export default function WmsShortReceiveDialog({
  line,
  initialQuantity,
  isLoading,
  serverError,
  onConfirm,
  onCancel,
  hidden,
}: Props) {
  const { t } = useTranslation("warehouse");
  // The line's final total, prefilled with what the scans already recorded:
  // a worker who scanned 7 of 10 sees 7 and corrects it to the number they
  // counted, instead of guessing whether the window wants 7, 3 or 10.
  const scanned = Number(line.received_quantity ?? 0);
  const expected = Number(line.expected_quantity ?? 0);
  const remaining = Math.max(expected - scanned, 0);
  const [quantity, setQuantity] = useState(
    String(startingTotal(initialQuantity, scanned)),
  );
  // How much of the counted total is received but not usable. Zero keeps the
  // old meaning of the code: it explains why the rest never arrived.
  const [held, setHeld] = useState(String(line.held_quantity ?? 0));
  // A whole damaged delivery is one answer, not a number typed twice: the
  // count follows what arrived, and "all of it" follows the count.
  const [heldAll, setHeldAll] = useState(false);
  // null until somebody picks: the default reason follows the side of the
  // expected figure the typed quantity falls on — SHORTAGE below it,
  // SURPLUS above — and a deliberate choice is never overwritten.
  const [code, setCode] = useState<string | null>(null);
  // A total under the scans is allowed only when it says it replaces them:
  // the record must not quietly lose goods somebody already handled.
  const [replaceScans, setReplaceScans] = useState(false);
  const [note, setNote] = useState("");
  const [validationError, setValidationError] = useState<string | null>(null);
  const unitSymbol = line.uom_symbol;

  const qty = Number(quantity);
  const typedHeld = Number(held);
  const heldValue = heldAll ? quantity : held;
  const heldQty = Number(heldValue);
  const holds = Number.isFinite(heldQty) && heldQty > 0;
  const isExact = Number.isFinite(qty) && qty === expected;
  const isOver = Number.isFinite(qty) && qty > expected;
  // Held goods say why they are not usable; a count with none held explains
  // the gap instead — short below the expectation, surplus above it.
  const defaultCode = holds ? "DAMAGE" : isOver ? "SURPLUS" : "SHORTAGE";
  const codeChoices = holds ? DOCUMENT_HELD_CODES : DOCUMENT_DISCREPANCY_CODES;
  // A choice the narrowed list no longer offers gives way to the default: the
  // field cannot show it, so sending it would send a reason nobody sees.
  const effectiveCode =
    code !== null && codeChoices.some((c) => c === code) ? code : defaultCode;
  // The field holds a number. An empty box parses as 0, and 0 is an answer
  // of its own — nothing arrived — so the emptiness, not the zero, is what
  // makes a field still unanswered.
  const entered = quantity.trim() !== "" && Number.isFinite(qty);
  const isBelowScanned = entered && qty < scanned;
  // A line that lands exactly on the expected figure carries no
  // discrepancy — the backend stores NULL for it anyway, so asking for a
  // code forces a lie. Everything else says why, a zero included: an
  // arrival of nothing is the shortage itself.
  // A held quantity is itself a reason, so the code shows even when the
  // count lands exactly on the expected figure.
  const showsDiscrepancy = entered && (!isExact || holds);
  const errorToShow = validationError ?? serverError;
  const showQuarantineGapHint = explainsAGapOnly(
    showsDiscrepancy,
    holds,
    effectiveCode,
  );

  const confirm = () => {
    if (!entered || qty < 0) {
      setValidationError(t("receiving.short.qtyRequired"));
      return;
    }
    if (!isValidHeldAnswer(heldAll, typedHeld)) {
      setValidationError(t("detail.heldQuantityAboveReceived"));
      return;
    }
    if (heldQty > qty) {
      setValidationError(t("detail.heldQuantityAboveReceived"));
      return;
    }
    if (isBelowScanned && !replaceScans) {
      setValidationError(t("receiving.short.belowScanned"));
      return;
    }
    // "Other" names nothing on its own, so the note is what carries the
    // reason — and the session is the only place it can still be asked.
    if (showsDiscrepancy && effectiveCode === "OTHER" && note.trim() === "") {
      setValidationError(t("receiving.short.noteRequired"));
      return;
    }
    onConfirm(
      line.id,
      qty,
      showsDiscrepancy ? effectiveCode : "",
      showsDiscrepancy ? note.trim() || undefined : undefined,
      isBelowScanned ? replaceScans : false,
      holds ? heldQty : 0,
    );
  };

  return (
    <Sheet
      open={!hidden}
      onClose={onCancel}
      zIndex="modal-nested"
      maxWidth="md"
      aria-label={t("receiving.short.title")}
    >
      <SheetBody className="p-5">
        <h3 className="text-base font-semibold text-on">
          {t("receiving.short.title")}
        </h3>
        <p className="mt-1 text-sm text-on-secondary">
          {line.product_name} —{" "}
          {t("receiving.short.expected", {
            expected: formatQuantityLocalized(t, expected, unitSymbol),
            scanned: formatQuantityLocalized(t, scanned, unitSymbol),
            remaining: formatQuantityLocalized(t, remaining, unitSymbol),
          })}
        </p>

        {errorToShow && (
          <p
            role="alert"
            className="mt-3 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700 dark:border-red-800/50 dark:bg-red-950/20 dark:text-red-300"
          >
            {errorToShow}
          </p>
        )}

        <div className="mt-4 space-y-3">
          <div>
            <label
              htmlFor="short-receive-qty"
              className="mb-1 block text-sm text-on-secondary"
            >
              {t("receiving.short.receivedQty")}
            </label>
            <QuantityInput
              id="short-receive-qty"
              uomSymbol={unitSymbol}
              min={0}
              data-testid="short-receive-qty"
              value={quantity}
              onChange={(e) => {
                setQuantity(e.target.value);
                setValidationError(null);
              }}
              autoFocus
            />
          </div>
          {isBelowScanned && (
            <Checkbox
              id="short-receive-replace-scans"
              checked={replaceScans}
              onChange={(e) => {
                setReplaceScans(e.target.checked);
                setValidationError(null);
              }}
              label={t("receiving.short.replacesScans")}
            />
          )}
          <div>
            <label
              htmlFor="short-receive-held"
              className="mb-1 block text-sm text-on-secondary"
            >
              {t("detail.heldQuantityLabel")}
            </label>
            <QuantityInput
              id="short-receive-held"
              uomSymbol={unitSymbol}
              min={0}
              data-testid="short-receive-held"
              aria-describedby="short-receive-held-hint"
              disabled={heldAll}
              value={heldValue}
              onChange={(e) => {
                setHeld(e.target.value);
                setValidationError(null);
              }}
            />
            <p
              id="short-receive-held-hint"
              className="mt-1 text-xs text-on-muted"
            >
              {t("receiving.short.heldHint")}
            </p>
            <div className="mt-2">
              <Checkbox
                id="short-receive-held-all"
                checked={heldAll}
                onChange={(e) => {
                  setHeldAll(e.target.checked);
                  setValidationError(null);
                }}
                label={t("receiving.short.allHeld")}
              />
            </div>
          </div>
          {showsDiscrepancy && (
            /* The shared control, so the field carries the same height, focus
               ring and label wiring as every other one — this was a bare
 `<select>` with a `<label>` pointing at nothing. */
            <NativeSelect
              label={t("receiving.short.discrepancy")}
              value={effectiveCode}
              onChange={(e) => setCode(e.target.value)}
            >
              {codeChoices.map((c) => (
                <option key={c} value={c}>
                  {t(`detail.discrepancyCodes.${c}`)}
                </option>
              ))}
            </NativeSelect>
          )}
          {/* Damage and Quality hold are both a reason for a gap and the
              reason goods in quarantine are in it. On a short line with
              nothing held they only explain the gap, and saying so is what
              keeps the worker from reading the code as a decision about the
              goods that did arrive. */}
          {showQuarantineGapHint && (
            <p className="text-xs text-on-muted">
              {t("receiving.short.quarantineCodeHint")}
            </p>
          )}
          {showsDiscrepancy && effectiveCode === "OTHER" && (
            <div>
              <label
                htmlFor="short-receive-note"
                className="mb-1 block text-sm text-on-secondary"
              >
                {t("receiving.short.note")}
              </label>
              <Input
                id="short-receive-note"
                value={note}
                onChange={(e) => {
                  setNote(e.target.value);
                  setValidationError(null);
                }}
                placeholder={t("receiving.short.notePlaceholder")}
                data-testid="short-receive-note"
              />
            </div>
          )}
        </div>

        {/* Skipping a line is the row's own action, with an icon beside
            the line it skips. This dialog exists to record what actually
            arrived; offering the same verb a second time here made two
            answers to one question. */}
        <SheetActions className="mt-5">
          <Button variant="ghost" onClick={onCancel} disabled={isLoading}>
            {t("common:form.cancel")}
          </Button>
          <Button onClick={confirm} disabled={isLoading} className="gap-1">
            {isLoading && <Loader2 size={14} className="animate-spin" />}
            {t("receiving.short.confirm")}
          </Button>
        </SheetActions>
      </SheetBody>
    </Sheet>
  );
}
