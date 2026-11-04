import { useState, type ReactNode } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { CircleCheck, Hourglass, Printer, RotateCcw } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { extractApiError } from "@/lib/errors";
import { useUndoDocument } from "@/modules/warehouse/hooks/useDocuments";
import { downloadDocumentPdf } from "@/modules/warehouse/lib/downloadDocumentPdf";
import {
  UNDOABLE_DOCUMENT_TYPES,
  undoLabelKey,
  type WarehouseDocument,
} from "@/modules/warehouse/types";

/** The action the screen performed, which decides the words. */
export type PostedAction = "receive" | "issue" | "writeOff" | "move";

interface PostedActionResultProps {
  /** The document the one-step post answered with. */
  document: WarehouseDocument;
  action: PostedAction;
  /** How many lines the person entered; a dispatch from a zone may come
   * back split over shelves, which is not what they counted. */
  lineCount?: number;
  /** A sentence of the caller's own under the outcome (an order's state). */
  details?: ReactNode;
  /** Buttons of the caller's own beside Print (labels, a packing slip). */
  extraActions?: ReactNode;
  /** The receiving area the goods stand in, when they wait there for putaway. */
  waitingIn?: string | null;
  /** Start the same action again on an empty screen. */
  onAnother: () => void;
}

/** The headline: what moved, that it waits for an approval, or that it was undone. */
function headline(
  t: (key: string, options?: Record<string, unknown>) => string,
  action: PostedAction,
  pending: boolean,
  count: number,
  undone: boolean,
): string {
  if (pending) return t("posted.pendingTitle");
  switch (action) {
    case "receive":
      return undone
        ? t("posted.receive.undoneTitle")
        : t("posted.receive.title", { count });
    case "issue":
      return undone
        ? t("posted.issue.undoneTitle")
        : t("posted.issue.title", { count });
    case "writeOff":
      return undone
        ? t("posted.writeOff.undoneTitle")
        : t("posted.writeOff.title", { count });
    default:
      return undone
        ? t("posted.move.undoneTitle")
        : t("posted.move.title", { count });
  }
}

/** What happened to the stock, in a sentence that names the document. */
function outcome(
  t: (key: string, options?: Record<string, unknown>) => string,
  action: PostedAction,
  pending: boolean,
  undone: boolean,
  waitingIn: string | null,
): string {
  if (pending) return t("posted.pendingBody");
  if (undone) return t("posted.undoneBody");
  switch (action) {
    case "receive":
      return waitingIn
        ? t("posted.receive.bodyWaiting", { location: waitingIn })
        : t("posted.receive.body");
    case "issue":
      return t("posted.issue.body");
    case "writeOff":
      return t("posted.writeOff.body");
    default:
      return t("posted.move.body");
  }
}

/** What Undo will do, said before the press rather than after it. */
function undoHint(
  t: (key: string, options?: Record<string, unknown>) => string,
  type: string,
  number: string,
): string {
  if (type === "INT") return t("posted.undoHintMove", { number });
  if (type === "IN" || type === "INTERNAL_IN") {
    return t("posted.undoHintReceive", { number });
  }
  return t("posted.undoHintIssue", { number });
}

/** The word the primary button wears for this action. */
function another(
  t: (key: string, options?: Record<string, unknown>) => string,
  action: PostedAction,
): string {
  switch (action) {
    case "receive":
      return t("posted.receive.another");
    case "issue":
      return t("posted.issue.another");
    case "writeOff":
      return t("posted.writeOff.another");
    default:
      return t("posted.move.another");
  }
}

/**
 * The answer of a one-screen action once the document is posted: what moved,
 * the document the office got (linked), Print, and Undo with the sentence
 * that says what undoing does. A document an approval stops says that the
 * stock moves when it is approved instead, and offers no undo — there is
 * nothing posted to reverse yet.
 */
export function PostedActionResult({
  document,
  action: requested,
  lineCount,
  details,
  extraActions,
  waitingIn = null,
  onAnother,
}: PostedActionResultProps) {
  const { t } = useTranslation(["warehouse", "common"]);
  const navigate = useNavigate();
  const undo = useUndoDocument();
  const [reversal, setReversal] = useState<WarehouseDocument | null>(null);
  const [undoError, setUndoError] = useState<string | null>(null);
  const [printing, setPrinting] = useState(false);
  // A write-off is booked on the issue screen, but it is not an issue: its
  // answer names what was done instead of the goods having been "issued".
  const action =
    requested === "issue" && document.type === "SCRAP" ? "writeOff" : requested;
  const pending = document.status === "PENDING_APPROVAL";
  const count = lineCount ?? document.lines?.length ?? 0;
  const canUndo =
    !pending && !reversal && UNDOABLE_DOCUMENT_TYPES.has(document.type);
  // Once the reversal is posted the heading and the sentence under it tell
  // the undo: "Issued 1 line — the goods have left stock" above "Undone"
  // said two opposite things. An undo waiting for approval has moved
  // nothing yet, so the posting still stands as told.
  const undone = reversal !== null && reversal.status !== "PENDING_APPROVAL";
  const number = (
    <Link
      to={`/warehouse/documents/${document.id}`}
      className="font-semibold text-primary-600 hover:underline"
    >
      {document.number}
    </Link>
  );

  const runUndo = () => {
    setUndoError(null);
    undo.mutate(document.id, {
      onSuccess: (answer) => setReversal(answer),
      onError: (error) =>
        setUndoError(extractApiError(error, t("errors.undoFailed"))),
    });
  };

  return (
    <Card className="space-y-4 p-4 md:p-6" aria-live="polite">
      <div className="flex items-start gap-3">
        {undone ? (
          <RotateCcw
            size={24}
            aria-hidden="true"
            className="mt-0.5 shrink-0 text-on-secondary"
          />
        ) : pending ? (
          <Hourglass
            size={24}
            aria-hidden="true"
            className="mt-0.5 shrink-0 text-on-warning"
          />
        ) : (
          <CircleCheck
            size={24}
            aria-hidden="true"
            className="mt-0.5 shrink-0 text-success-600"
          />
        )}
        <div className="min-w-0 space-y-1">
          <h2 className="text-lg font-semibold text-on">
            {headline(t, action, pending, count, undone)}
          </h2>
          <p className="text-sm text-on-secondary">
            {outcome(t, action, pending, undone, waitingIn)}{" "}
            {t("posted.documentIs")} {number}.
          </p>
          {/* The reversal owns the story once it exists: a sentence about the
              order's state was true at posting time and is not any more. */}
          {details && !reversal && (
            <p className="text-sm text-on-secondary">{details}</p>
          )}
        </div>
      </div>

      {reversal && (
        <p
          role="status"
          className="rounded-lg bg-success-50 px-3 py-2 text-sm text-on-success"
        >
          {reversal.status === "PENDING_APPROVAL"
            ? t("toast.undoPendingApproval", { number: reversal.number ?? "" })
            : t("toast.undone", { number: reversal.number ?? "" })}{" "}
          <Link
            to={`/warehouse/documents/${reversal.id}`}
            className="font-semibold underline"
          >
            {t("actions.viewReversal")}
          </Link>
        </p>
      )}

      <div className="flex flex-wrap gap-2">
        <Button onClick={onAnother}>{another(t, action)}</Button>
        <Button variant="outline" onClick={() => navigate("/warehouse/todo")}>
          {t("posted.backToStart")}
        </Button>
        <Button
          variant="outline"
          leftIcon={<Printer size={16} />}
          disabled={printing}
          onClick={() => void downloadDocumentPdf(document, t, setPrinting)}
        >
          {t("posted.print", { number: document.number })}
        </Button>
        {extraActions}
      </div>

      {canUndo && (
        <div className="space-y-2 border-t border-border pt-4">
          <Button
            variant="outline"
            leftIcon={<RotateCcw size={16} />}
            disabled={undo.isPending}
            aria-describedby="posted-undo-hint"
            onClick={runUndo}
          >
            {t(undoLabelKey(document.type))}
          </Button>
          <p id="posted-undo-hint" className="text-sm text-on-muted">
            {undoHint(t, document.type, document.number)}
          </p>
          {undoError && (
            <p role="alert" className="text-sm text-on-danger">
              {undoError}
            </p>
          )}
        </div>
      )}
    </Card>
  );
}
