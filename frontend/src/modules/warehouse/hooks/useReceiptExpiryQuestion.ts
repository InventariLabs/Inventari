import { useCallback, useState } from "react";
import { extractApiErrorCode, extractApiErrorRows } from "@/lib/errors";
import type {
  DocumentCompletePayload,
  DocumentTrackingPayload,
  WarehouseDocument,
} from "@/modules/warehouse/types";

/** The lot and expiry the worker read off a pack for one undated line. */
interface ExpiryAnswer {
  batchNumber: string;
  expiryDate: string;
}

/** Which door asked: a completion resends its payload, a one-step posting
 * resends only the lot and expiry. */
type ExpiryMode = "complete" | "post";

interface Question {
  mode: ExpiryMode;
  payload: DocumentCompletePayload;
  remaining: { lineId: string; product: string }[];
  answers: Record<string, ExpiryAnswer>;
}

/** What the page needs to render the question: one line at a time. The line
 * id lets the sheet start blank for each line — the same product twice is
 * still two packs to read, never the previous answer carried over. */
export interface ReceiptExpiryPrompt {
  prompt: { lineId: string; product: string };
  onConfirm: (batchNumber: string, expiryDate: string) => void;
  onClose: () => void;
}

interface CompletionCall {
  id: string;
  data?: DocumentCompletePayload;
}

interface PostingCall {
  id: string;
  data?: DocumentTrackingPayload;
}

interface UseReceiptExpiryQuestionOptions {
  doc: WarehouseDocument | undefined;
  docId: string | undefined;
  /** The two mutations that can be refused this way. */
  complete: (
    call: CompletionCall,
    opts: {
      onSuccess?: (data?: WarehouseDocument) => void;
      onError?: (err: unknown) => void;
    },
  ) => void;
  postNow: (
    call: PostingCall,
    opts: {
      onSuccess?: (data?: WarehouseDocument) => void;
      onError?: (err: unknown) => void;
    },
  ) => void;
  onCompleted: (data?: WarehouseDocument) => void;
  onPosted: (data?: WarehouseDocument) => void;
  /** What to do with a completion refusal that is not this question — a
   * record kept in another unit, or a sentence for the reader. */
  onCompletionRefused: (err: unknown, payload: DocumentCompletePayload) => void;
  /** The one-step posting's own refusal, when it is not this question. */
  onPostingRefused: (err: unknown) => void;
}

/**
 * The payload a completion is retried with once the lot and expiry are read.
 *
 * It starts from the lines the caller answered. A completion that named none
 * — a finished session's close — keeps every line's quantity from the
 * document, because a payload naming only the dated lines would book the
 * others as delivered in full. A date lands only on the lines the server
 * named, exactly as the receiving screen keeps a scan's.
 */
function linesWithDates(
  doc: WarehouseDocument | undefined,
  payload: DocumentCompletePayload,
  answers: Record<string, ExpiryAnswer>,
): DocumentCompletePayload["lines"] {
  const base: NonNullable<DocumentCompletePayload["lines"]> =
    payload.lines && payload.lines.length > 0
      ? payload.lines.map((line) => ({ ...line }))
      : (doc?.lines ?? []).map((line) => ({
          line_id: line.id,
          done_quantity: Number(line.done_quantity ?? 0),
          ...(Number(line.held_quantity ?? 0) > 0
            ? { held_quantity: Number(line.held_quantity) }
            : {}),
          ...(line.discrepancy_code
            ? {
                discrepancy_code: line.discrepancy_code,
                ...(line.discrepancy_reason
                  ? { discrepancy_reason: line.discrepancy_reason }
                  : {}),
              }
            : {}),
        }));

  const dated = base.map((line) => {
    const answer = answers[line.line_id];
    if (!answer) return line;
    return {
      ...line,
      expiry_date: answer.expiryDate,
      ...(answer.batchNumber ? { batch_number: answer.batchNumber } : {}),
    };
  });
  // A line the body left out but the refusal named — a session wrote its
  // quantity before this completion — keeps that quantity and gains a date.
  for (const [lineId, answer] of Object.entries(answers)) {
    if (dated.some((line) => line.line_id === lineId)) continue;
    const docLine = doc?.lines.find((line) => line.id === lineId);
    dated.push({
      line_id: lineId,
      done_quantity: Number(docLine?.done_quantity ?? 0),
      expiry_date: answer.expiryDate,
      ...(answer.batchNumber ? { batch_number: answer.batchNumber } : {}),
    });
  }
  return dated;
}

/** The undated lines a `RECEIPT_EXPIRY_REQUIRED` refusal named. */
function undatedLinesFrom(err: unknown): { lineId: string; product: string }[] {
  return (extractApiErrorRows(err, "lines") ?? [])
    .map((row) => ({
      lineId: String(row.line_id ?? ""),
      product: String(row.product ?? ""),
    }))
    .filter((row) => row.lineId !== "");
}

/**
 * The lot-and-expiry question a receipt raises when a FEFO line has no date.
 *
 * The refusal names every undated line; the sheet asks for one line at a
 * time, and the last answer resends the door that asked — the completion
 * with its payload, a one-step posting with the tracking body it accepts.
 * The state and the retry live here so the two doors share one copy of the
 * wording and the logic.
 */
export function useReceiptExpiryQuestion({
  doc,
  docId,
  complete,
  postNow,
  onCompleted,
  onPosted,
  onCompletionRefused,
  onPostingRefused,
}: UseReceiptExpiryQuestionOptions) {
  const [question, setQuestion] = useState<Question | null>(null);

  /** Open the question if *err* is the expiry refusal; false otherwise. */
  const askFromError = useCallback(
    (mode: ExpiryMode, payload: DocumentCompletePayload, err: unknown) => {
      if (extractApiErrorCode(err) !== "RECEIPT_EXPIRY_REQUIRED") return false;
      const remaining = undatedLinesFrom(err);
      if (remaining.length === 0) return false;
      setQuestion({ mode, payload, remaining, answers: {} });
      return true;
    },
    [],
  );

  const handleCompletionError = useCallback(
    (err: unknown, payload: DocumentCompletePayload) => {
      if (askFromError("complete", payload, err)) return;
      onCompletionRefused(err, payload);
    },
    [askFromError, onCompletionRefused],
  );

  const dismiss = useCallback(() => setQuestion(null), []);

  const answer = useCallback(
    (batchNumber: string, expiryDate: string) => {
      if (!question || !docId) return;
      const [current, ...remaining] = question.remaining;
      if (!current) return;
      const answers = {
        ...question.answers,
        [current.lineId]: { batchNumber, expiryDate },
      };
      // Another undated line keeps the sheet up; the last answer resends the
      // call that asked with every date that was read.
      if (remaining.length > 0) {
        setQuestion({ ...question, remaining, answers });
        return;
      }
      setQuestion(null);
      if (question.mode === "post") {
        postNow(
          {
            id: docId,
            data: {
              lines: Object.entries(answers).map(([lineId, value]) => ({
                line_id: lineId,
                ...(value.batchNumber
                  ? { batch_number: value.batchNumber }
                  : {}),
                expiry_date: value.expiryDate,
              })),
            },
          },
          {
            onSuccess: onPosted,
            onError: (err) => {
              if (!askFromError("post", {}, err)) onPostingRefused(err);
            },
          },
        );
        return;
      }
      const datedPayload = {
        ...question.payload,
        lines: linesWithDates(doc, question.payload, answers),
      };
      complete(
        { id: docId, data: datedPayload },
        {
          onSuccess: onCompleted,
          onError: (err) => handleCompletionError(err, datedPayload),
        },
      );
    },
    [
      question,
      docId,
      doc,
      complete,
      postNow,
      onCompleted,
      onPosted,
      askFromError,
      handleCompletionError,
      onPostingRefused,
    ],
  );

  const current = question?.remaining[0];
  const prompt: ReceiptExpiryPrompt | null = question
    ? {
        prompt: {
          lineId: current?.lineId ?? "",
          product: current?.product ?? "",
        },
        onConfirm: answer,
        onClose: dismiss,
      }
    : null;

  return { askFromError, handleCompletionError, dismiss, prompt };
}
