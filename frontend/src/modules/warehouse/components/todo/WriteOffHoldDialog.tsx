import { useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { Button } from "@/components/ui/Button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/Dialog";
import { extractApiError } from "@/lib/errors";
import { formatQuantityLocalized } from "@/lib/i18nHelpers";
import { ReasonCodeField } from "@/modules/shared/components/ReasonCodeField";
import { usePostNewDocument } from "@/modules/warehouse/hooks/useDocuments";
import {
  SCRAP_REASON_CODES,
  type ScrapReasonCode,
} from "@/modules/warehouse/reasonCodes";
import type { QuarantineHold } from "@/modules/warehouse/types";

/** The write-off reason a hold's own reason already implies. */
function suggestedReason(
  held: string | null | undefined,
): ScrapReasonCode | "" {
  if (held === "DAMAGE") return "DAMAGED";
  if (held === "QUALITY_HOLD") return "QUALITY";
  return "";
}

/**
 * Writes a batchless hold off in one step, the way Issue goods does for
 * "Damaged or expired": the reader says why, the write-off document is
 * created and posted together, and the goods leave the quarantine shelf.
 * The office's New Document form stays for the cases that need it.
 */
export default function WriteOffHoldDialog({
  hold,
  onClose,
}: {
  hold: QuarantineHold;
  onClose: () => void;
}) {
  const { t } = useTranslation("warehouse");
  const post = usePostNewDocument();
  const [code, setCode] = useState<ScrapReasonCode | "">(
    suggestedReason(hold.reason),
  );
  const [note, setNote] = useState("");
  const [attempted, setAttempted] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // One press, one key: a retry after a lost answer posts once.
  const key = useRef(crypto.randomUUID());
  const quantity = formatQuantityLocalized(t, hold.quantity, hold.uom_symbol);
  const product = hold.product_name ?? hold.name;
  const incomplete = code === "" || (code === "OTHER" && note.trim() === "");

  const submit = () => {
    setAttempted(true);
    setError(null);
    if (incomplete) return;
    post.mutate(
      {
        key: key.current,
        data: {
          type: "SCRAP",
          source_location_id: hold.location_id ?? undefined,
          reason_code: code,
          notes: note.trim() || undefined,
          lines: [
            {
              item_id: hold.item_id ?? undefined,
              product_template_id: hold.product_template_id ?? undefined,
              name: hold.product_name ?? undefined,
              expected_quantity: Number(hold.quantity),
            },
          ],
        },
      },
      {
        onSuccess: (posted) => {
          // A workflow that wants approval parks the document: nothing has
          // left the shelf yet, so "Wrote off" would be untrue.
          toast.success(
            posted.status === "PENDING_APPROVAL"
              ? t("toast.pendingApproval")
              : t("todo.writeOffDone", { product, quantity }),
          );
          onClose();
        },
        onError: (e) => setError(extractApiError(e, t("errors.postNowFailed"))),
      },
    );
  };

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>
            {t("todo.decisionWriteOff")}: {product}
          </DialogTitle>
          <DialogDescription>
            {t("todo.writeOffBody", {
              quantity,
              location: hold.location_name ?? "",
            })}
          </DialogDescription>
        </DialogHeader>
        <ReasonCodeField
          testId="hold-write-off-reason"
          label={t("reasons.scrap.label")}
          codes={SCRAP_REASON_CODES}
          labelFor={(c) => t(`reasons.scrap.codes.${c}`)}
          code={code}
          onCodeChange={setCode}
          note={note}
          onNoteChange={setNote}
          showErrors={attempted}
        />
        {error && (
          <p role="alert" className="text-sm text-on-danger">
            {error}
          </p>
        )}
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            {t("actions.cancel")}
          </Button>
          <Button onClick={submit} isLoading={post.isPending}>
            {t("todo.decisionWriteOff")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
