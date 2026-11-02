import { useEffect, useRef } from "react";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import LoadingSpinner from "@/components/LoadingSpinner";
import { Button } from "@/components/ui/Button";
import { Sheet, SheetBody, SheetHeader } from "@/components/ui/Sheet";
import { extractApiError } from "@/lib/errors";
import type { WmsReceiveLine } from "@/modules/warehouse/api/documents_receiving";
import { PostedActionResult } from "@/modules/warehouse/components/actions/PostedActionResult";
import { useCompleteDocument } from "@/modules/warehouse/hooks/useDocuments";
import type { WarehouseDocument } from "@/modules/warehouse/types";

// The saved answers after which the server opens a backorder for a line that
// has no order behind it (BACKORDER_CODES in the backend).
const BACKORDER_CODES: ReadonlySet<string> = new Set([
  "SHORTAGE",
  "DAMAGE",
  "QUALITY_HOLD",
]);

interface Props {
  documentId: string;
  lines: WmsReceiveLine[];
  onClose: () => void;
}

/**
 * The end of a delivery received on a phone: the goods go into stock as
 * soon as the last item is confirmed — the worker pressed "finish", and a
 * second summary to close before anything is booked is one tap too many on
 * the floor. What follows is the answer the one-screen receive gives: the
 * document the office got, the next task, and Undo, which writes the
 * reversing correction.
 */
export default function WmsReceivingPhoneDone({
  documentId,
  lines,
  onClose,
}: Props) {
  const { t } = useTranslation(["warehouse", "common"]);
  const navigate = useNavigate();
  const complete = useCompleteDocument();
  // Once per screen: a second mount in StrictMode must not post twice.
  const asked = useRef(false);
  const post = complete.mutate;
  useEffect(() => {
    if (asked.current) return;
    asked.current = true;
    post({ id: documentId });
  }, [post, documentId]);

  const received = lines.filter((ln) => ln.received_quantity > 0).length;
  const missingLines = lines.filter(
    (ln) => ln.received_quantity < ln.expected_quantity,
  );
  const missing = missingLines.length > 0;
  // What the missing goods become depends on what the server did with each
  // line, not on the screen having said "missing": an order still owes its
  // lines, a receipt without one gets a backorder only for a line whose
  // saved answer asks for it (Shortage, Damaged, Quality hold), and the rest
  // ("Not coming") is closed. One sentence per outcome; when the lines ended
  // differently, none of those sentences is true of all of them.
  const missingDetails = (posted: WarehouseDocument) => {
    const total = lines.length;
    const codeOf = new Map(
      posted.lines.map((ln) => [ln.id, ln.discrepancy_code]),
    );
    const outcomes = new Set(
      missingLines.map((ln) => {
        if (ln.from_order) return "order";
        const code = codeOf.get(ln.document_line_id);
        return posted.generated_backorder_id &&
          code &&
          BACKORDER_CODES.has(code)
          ? "backorder"
          : "closed";
      }),
    );
    if (outcomes.has("closed") && outcomes.size > 1)
      return t("receiving.phone.doneMissingMixed", { received, total });
    if (outcomes.size > 1)
      // Order and backorder: nothing is closed, it is expected in two places.
      return t("receiving.phone.doneMissingTwoPlaces", {
        received,
        total,
        number: posted.generated_backorder_number ?? "",
      });
    if (outcomes.has("order"))
      return t("receiving.phone.doneMissing", { received, total });
    if (outcomes.has("backorder"))
      return t("receiving.phone.doneMissingBackorder", {
        received,
        total,
        number: posted.generated_backorder_number ?? "",
      });
    return t("receiving.phone.doneMissingClosed", { received, total });
  };

  return (
    <Sheet
      open
      onClose={onClose}
      zIndex="modal"
      maxWidth="md"
      fullBleedOnMobile
      aria-label={t("receiving.title")}
    >
      <SheetHeader title={t("receiving.title")} onClose={onClose} />
      <SheetBody className="p-4">
        {complete.data ? (
          <PostedActionResult
            document={complete.data}
            action="receive"
            lineCount={received}
            details={missing ? missingDetails(complete.data) : undefined}
            onAnother={() => navigate("/warehouse/receive")}
          />
        ) : complete.isError ? (
          <div className="space-y-3">
            <p role="alert" className="text-sm text-on-danger">
              {extractApiError(complete.error, t("errors.completeFailed"))}
            </p>
            <Button onClick={() => post({ id: documentId })}>
              {t("receiving.error.retry")}
            </Button>
          </div>
        ) : (
          <div className="flex flex-col items-center gap-3 py-10">
            <LoadingSpinner />
            <p className="text-sm text-on-secondary">
              {t("receiving.phone.posting")}
            </p>
          </div>
        )}
      </SheetBody>
    </Sheet>
  );
}
