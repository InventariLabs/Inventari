import { useState, useCallback, useEffect } from "react";
import type { TFunction } from "i18next";
import type {
  DocumentCompletePayload,
  DocumentDiscrepancyCode,
  WarehouseDocument,
} from "@/modules/warehouse/types";
import { DOCUMENT_HELD_CODES } from "@/modules/warehouse/discrepancyCodes";
import { getDocumentLineStatus } from "@/modules/warehouse/lineStatus";
import { formatDecimalQty } from "@/utils/formatters";
import { unitLabel } from "@/lib/i18nHelpers";

export type ExecutionLine = WarehouseDocument["lines"][number];

interface UseDocumentExecutionOptions {
  document: WarehouseDocument;
  onSubmit: (data: DocumentCompletePayload) => void;
  t: TFunction;
}

/**
 * How much of a line is done, as the field shows it. Every reader of the
 * screen asks here: a line nobody has typed into yet has done nothing, which
 * is also what the server reports for an untouched line (`done_quantity` is
 * required in the contract), so "no entry" and "zero" are one answer.
 */
export function typedDoneQuantity(
  values: Record<string, string>,
  lineId: string,
): string {
  return values[lineId] ?? "0";
}

function buildInitialDoneValues(
  document: WarehouseDocument,
): Record<string, string> {
  return Object.fromEntries(
    document.lines.map((line) => {
      const initialValue = line.done_quantity;
      // The wire carries a column's own scale, not a number anybody typed:
      // ten pieces arrive as "10.000". Handed to the field as it came, the
      // digits read as ten thousand to one reader and as a piece count with
      // three decimals to another. The padding is the database's, so it is
      // stripped here — the same answer `formatDecimalQty` gives every other
      // screen that shows this value.
      return [line.id, formatDecimalQty(initialValue)];
    }),
  );
}

function buildInitialHeldValues(
  document: WarehouseDocument,
): Record<string, string> {
  return Object.fromEntries(
    document.lines.map((line) => [
      line.id,
      formatDecimalQty(line.held_quantity ?? 0),
    ]),
  );
}

function getExpectedQuantity(line: WarehouseDocument["lines"][number]): number {
  return Number(line.expected_quantity ?? line.quantity);
}

function getLineDisplayName(line: WarehouseDocument["lines"][number]): string {
  return line.name?.trim() || line.barcode || line.id;
}

interface CompletionDraft {
  lines: DocumentCompletePayload["lines"];
  codeErrors: Record<string, string>;
  missingHeldCode: boolean;
  error: string | null;
}

/**
 * The completion payload, and every reason the screen cannot send it yet.
 *
 * Outside the hook because it is arithmetic and validation, not state: the
 * hook holds what was typed, this decides whether it means anything. A held
 * quantity is a discrepancy of its own — a held line needs one of the two
 * codes that mean "not for the shelf" even when the delivery is full.
 */
function buildCompletionDraft(
  document: WarehouseDocument,
  values: Record<string, string>,
  heldValues: Record<string, string>,
  codes: Record<string, DocumentDiscrepancyCode | "">,
  reasons: Record<string, string>,
  t: TFunction,
): CompletionDraft {
  const lines: DocumentCompletePayload["lines"] = [];
  const codeErrors: Record<string, string> = {};
  const noError: CompletionDraft = {
    lines,
    codeErrors,
    missingHeldCode: false,
    error: null,
  };

  for (const line of document.lines) {
    const doneQuantity = Number(values[line.id] ?? "0");
    const expectedQuantity = getExpectedQuantity(line);
    const discrepancyCode = codes[line.id] ?? "";
    const discrepancyReason = reasons[line.id]?.trim() ?? "";
    const heldQuantity = Number(heldValues[line.id] ?? "0");

    if (!Number.isFinite(doneQuantity) || doneQuantity < 0) {
      return {
        ...noError,
        error: t("warehouse:detail.executionInvalidQuantity"),
      };
    }
    if (doneQuantity > expectedQuantity) {
      return { ...noError, error: t("warehouse:detail.executionTooHigh") };
    }
    if (!Number.isFinite(heldQuantity) || heldQuantity < 0) {
      return {
        ...noError,
        error: t("warehouse:detail.executionInvalidQuantity"),
      };
    }
    if (heldQuantity > doneQuantity) {
      return {
        ...noError,
        error: t("warehouse:detail.heldQuantityAboveReceived"),
      };
    }

    const needsCode = doneQuantity < expectedQuantity || heldQuantity > 0;
    if (heldQuantity > 0) {
      // A held quantity says the goods are damaged or waiting for a quality
      // decision; any other code would quarantine them under a reason that
      // does not mean that.
      if (
        !DOCUMENT_HELD_CODES.includes(
          discrepancyCode as DocumentDiscrepancyCode,
        )
      ) {
        codeErrors[line.id] = t("warehouse:detail.heldQuantityNeedsCode");
        noError.missingHeldCode = true;
      }
    } else if (doneQuantity < expectedQuantity && !discrepancyCode) {
      codeErrors[line.id] = t("warehouse:detail.executionCodeRequired");
    }

    lines.push({
      line_id: line.id,
      done_quantity: doneQuantity,
      ...(heldQuantity > 0 ? { held_quantity: heldQuantity } : {}),
      ...(needsCode
        ? {
            discrepancy_code: discrepancyCode as DocumentDiscrepancyCode,
            ...(discrepancyReason
              ? { discrepancy_reason: discrepancyReason }
              : {}),
          }
        : {}),
    });
  }

  return noError;
}

function countLineStatuses(
  document: WarehouseDocument,
  values: Record<string, string>,
  codes: Record<string, DocumentDiscrepancyCode | "">,
) {
  const doneOf = (lineId: string) => {
    const parsed = Number(typedDoneQuantity(values, lineId));
    return Number.isFinite(parsed) ? parsed : 0;
  };
  return document.lines.reduce(
    (counts, line) => {
      const status = getDocumentLineStatus(
        {
          ...line,
          done_quantity: doneOf(line.id),
          discrepancy_code: (codes[line.id] || line.discrepancy_code) ?? null,
        },
        document.status,
      );
      counts[status] += 1;
      return counts;
    },
    { PENDING: 0, DONE: 0, PARTIAL: 0, EXCEPTION: 0 } satisfies Record<
      "PENDING" | "DONE" | "PARTIAL" | "EXCEPTION",
      number
    >,
  );
}

export function useDocumentExecution({
  document,
  onSubmit,
  t,
}: UseDocumentExecutionOptions) {
  const [values, setValues] = useState<Record<string, string>>({});
  const [codes, setCodes] = useState<
    Record<string, DocumentDiscrepancyCode | "">
  >({});
  // How much of each line's received quantity is held back. Empty is zero:
  // a line that never mentions damage has none.
  const [heldValues, setHeldValues] = useState<Record<string, string>>({});
  // per-line "code required" errors rendered next to the field.
  const [codeErrors, setCodeErrors] = useState<Record<string, string>>({});
  const [reasons, setReasons] = useState<Record<string, string>>({});
  const [reasonEditorOpen, setReasonEditorOpen] = useState<
    Record<string, boolean>
  >({});
  const [scanMode, setScanMode] = useState(false);
  const [cameraOpen, setCameraOpen] = useState(false);
  const [scanValue, setScanValue] = useState("");
  // Two readings of "the line just handled", kept apart on purpose.
  //
  // ``lastScannedLineId`` is the cursor every quantity action moves — typed,
  // filled, scanned — and the panel advances the focus by it. The badge,
  // though, claims a *scan*: feeding it the same cursor stamped "Recently
  // Scanned" on a line whose number came from the keyboard. ``scannedLineId``
  // follows scans alone and goes out with the first keystroke after one.
  const [lastScannedLineId, setLastScannedLineId] = useState<string | null>(
    null,
  );
  const [scannedLineId, setScannedLineId] = useState<string | null>(null);
  const [scanFeedback, setScanFeedback] = useState<string | null>(null);
  const [scanFeedbackTone, setScanFeedbackTone] = useState<"neutral" | "error">(
    "neutral",
  );
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setValues(buildInitialDoneValues(document));
    setHeldValues(buildInitialHeldValues(document));
    setCodes(
      Object.fromEntries(
        document.lines.map((line) => [line.id, line.discrepancy_code ?? ""]),
      ) as Record<string, DocumentDiscrepancyCode | "">,
    );
    setReasons(
      Object.fromEntries(
        document.lines.map((line) => [line.id, line.discrepancy_reason ?? ""]),
      ),
    );
    setReasonEditorOpen(
      Object.fromEntries(
        document.lines.map((line) => [
          line.id,
          Boolean(line.discrepancy_reason?.trim()),
        ]),
      ),
    );
    setScanMode(false);
    setCameraOpen(false);
    setScanValue("");
    setLastScannedLineId(null);
    setScannedLineId(null);
    setScanFeedback(null);
    setScanFeedbackTone("neutral");
    setError(null);
  }, [document]);

  const getCurrentDoneQuantity = useCallback(
    (lineId: string) => {
      const rawValue = values[lineId] ?? "0";
      const parsedValue = Number(rawValue);
      return Number.isFinite(parsedValue) ? parsedValue : 0;
    },
    [values],
  );

  const scanTargetLine = lastScannedLineId
    ? (document.lines.find((line) => line.id === lastScannedLineId) ?? null)
    : null;

  const nextIncompleteLine =
    scanTargetLine &&
    getCurrentDoneQuantity(scanTargetLine.id) <
      getExpectedQuantity(scanTargetLine)
      ? scanTargetLine
      : (document.lines.find(
          (line) => getCurrentDoneQuantity(line.id) < getExpectedQuantity(line),
        ) ?? null);

  const activeScanLineId = scanMode ? (nextIncompleteLine?.id ?? null) : null;

  const clearLineState = useCallback((lineId: string) => {
    setCodes((current) => ({ ...current, [lineId]: "" }));
    setReasons((current) => ({ ...current, [lineId]: "" }));
    setReasonEditorOpen((current) => ({ ...current, [lineId]: false }));
  }, []);

  // One scan landing on a line; without a line, the reader is told why.
  const applyScanToLine = useCallback(
    (matchedLine: ExecutionLine | undefined, notFound: string) => {
      if (!matchedLine) {
        setScanFeedback(notFound);
        setScanFeedbackTone("error");
        return false;
      }
      const expectedQuantity = getExpectedQuantity(matchedLine);
      const doneQuantity = getCurrentDoneQuantity(matchedLine.id);
      const nextDoneQuantity = Math.min(doneQuantity + 1, expectedQuantity);
      const advanced = nextDoneQuantity !== doneQuantity;
      const name = getLineDisplayName(matchedLine);
      const heldQuantity = Number(heldValues[matchedLine.id] ?? "0");

      if (advanced) {
        setValues((current) => ({
          ...current,
          [matchedLine.id]: String(nextDoneQuantity),
        }));
        if (nextDoneQuantity >= expectedQuantity && !heldQuantity) {
          clearLineState(matchedLine.id);
        }
        setError(null);
      }
      setLastScannedLineId(matchedLine.id);
      setScannedLineId(matchedLine.id);
      setScanFeedback(
        advanced
          ? t("warehouse:detail.scanMatched", {
              name,
              done: nextDoneQuantity,
              expected: expectedQuantity,
              unit: unitLabel(t, matchedLine.uom?.symbol, expectedQuantity),
            })
          : t("warehouse:detail.scanAlreadyDone", { name }),
      );
      setScanFeedbackTone("neutral");
      setScanValue("");
      return true;
    },
    [getCurrentDoneQuantity, heldValues, clearLineState, t],
  );

  /**
   * Apply a scan to the document's own lines.
   *
   * Returns false when the code is not on this document — the panel then asks
   * the shared registry what it is, so a code from outside this context is
   * named rather than dismissed.
   */
  const applyScanCode = useCallback(
    (rawCode: string): boolean => {
      const trimmedCode = rawCode.trim();
      const normalizedCode = trimmedCode.toLowerCase();
      if (!normalizedCode) return true;

      return applyScanToLine(
        document.lines.find(
          (line) => line.barcode?.trim().toLowerCase() === normalizedCode,
        ),
        t("warehouse:detail.scanNotFound", { code: trimmedCode }),
      );
    },
    [document.lines, applyScanToLine, t],
  );

  const updateLineDoneQuantity = useCallback(
    (lineId: string, nextQuantity: number) => {
      const line = document.lines.find((l) => l.id === lineId);
      if (!line) return;

      const expectedQuantity = getExpectedQuantity(line);
      const clampedQuantity = Math.min(
        Math.max(nextQuantity, 0),
        expectedQuantity,
      );

      setValues((current) => ({
        ...current,
        [lineId]: String(clampedQuantity),
      }));
      // Nothing can be held back of a delivery that just got smaller.
      setHeldValues((current) => {
        const held = Number(current[lineId] ?? "0");
        if (!Number.isFinite(held) || held <= clampedQuantity) return current;
        return { ...current, [lineId]: String(clampedQuantity) };
      });

      const heldQuantity = Number(heldValues[lineId] ?? "0");
      if (clampedQuantity >= expectedQuantity && !heldQuantity) {
        clearLineState(lineId);
      }

      // The cursor moves — the panel advances the focus by it — but the
      // "recently scanned" badge does not: the number came from the
      // keyboard, and a keystroke takes back a scan's mark on the same line.
      setLastScannedLineId(lineId);
      setScannedLineId(null);
      setError(null);
    },
    [document.lines, heldValues, clearLineState],
  );

  const handleScanModeToggle = useCallback(() => {
    setScanMode((prev) => {
      const next = !prev;
      setCameraOpen(false);
      setValues(buildInitialDoneValues(document));
      setScanValue("");
      setLastScannedLineId(null);
      setScannedLineId(null);
      setScanFeedback(null);
      setScanFeedbackTone("neutral");
      setError(null);
      return next;
    });
  }, [document]);

  const handleCameraToggle = useCallback(
    (restartCamera: () => void, setIsCameraActive: (v: boolean) => void) => {
      setCameraOpen((prev) => {
        const next = !prev;
        if (next) {
          restartCamera();
        } else {
          setIsCameraActive(false);
        }
        return next;
      });
    },
    [],
  );

  const handleSubmit = useCallback(() => {
    const draft = buildCompletionDraft(
      document,
      values,
      heldValues,
      codes,
      reasons,
      t,
    );
    if (draft.error) {
      setError(draft.error);
      return;
    }
    if (Object.keys(draft.codeErrors).length > 0) {
      setCodeErrors(draft.codeErrors);
      setError(
        t(
          draft.missingHeldCode
            ? "warehouse:detail.heldQuantityNeedsCode"
            : "warehouse:detail.executionCodeRequired",
        ),
      );
      return;
    }

    setCodeErrors({});
    setError(null);
    onSubmit({ lines: draft.lines });
  }, [document, values, heldValues, codes, reasons, onSubmit, t]);

  const lineStatusCounts = countLineStatuses(document, values, codes);

  return {
    values,
    heldValues,
    codes,
    codeErrors,
    reasons,
    reasonEditorOpen,
    scanMode,
    cameraOpen,
    scanValue,
    lastScannedLineId,
    scannedLineId,
    scanFeedback,
    scanFeedbackTone,
    error,
    scanTargetLine,
    nextIncompleteLine,
    activeScanLineId,
    lineStatusCounts,
    getCurrentDoneQuantity,
    applyScanCode,
    applyScanToLine,
    updateLineDoneQuantity,
    handleScanModeToggle,
    handleCameraToggle,
    handleSubmit,
    setCodeForLine: (lineId: string, code: DocumentDiscrepancyCode | "") => {
      setCodes((current) => ({ ...current, [lineId]: code }));
      if (code) {
        setCodeErrors((current) => {
          if (!(lineId in current)) return current;
          const next = { ...current };
          delete next[lineId];
          return next;
        });
      }
    },
    toggleReasonEditor: (lineId: string) => {
      setReasonEditorOpen((current) => ({
        ...current,
        [lineId]: !current[lineId],
      }));
    },
    setReasonForLine: (lineId: string, reason: string) => {
      setReasons((current) => ({ ...current, [lineId]: reason }));
    },
    setHeldForLine: (lineId: string, quantity: number) => {
      const line = document.lines.find((l) => l.id === lineId);
      if (!line) return;
      const done = getCurrentDoneQuantity(lineId);
      const clamped = Math.min(Math.max(quantity, 0), done);
      setHeldValues((current) => ({ ...current, [lineId]: String(clamped) }));
      if (clamped > 0) {
        // Holding goods back is a decision about why; the codes that say so
        // are the only ones the server accepts beside a held quantity.
        setCodes((current) =>
          DOCUMENT_HELD_CODES.includes(
            current[lineId] as DocumentDiscrepancyCode,
          )
            ? current
            : { ...current, [lineId]: "DAMAGE" },
        );
      }
      setError(null);
    },
    setScanMode,
    setScanValue,
    setCameraOpen,
    setScanFeedback,
    setLastScannedLineId,
  };
}
