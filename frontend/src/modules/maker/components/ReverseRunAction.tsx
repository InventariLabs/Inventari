import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Undo2 } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/Button";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { useCanManage, useCanWrite } from "@/hooks/useCanWrite";
import { extractApiError } from "@/lib/errors";
import { useReverseProduction } from "@/modules/maker/hooks/useProduction";
import type { ProductionOrder } from "@/modules/maker/types/maker";

/**
 * "Undo run" on a completed run, with the question that comes before it.
 *
 * A completed run stays on record; undoing it writes the way back beside it —
 * the ingredients return to where they were taken from, the output leaves
 * its location — the way a receipt or an issue is undone in the warehouse.
 * A typo of 20 for 2 used to need one hand correction per ingredient and
 * shelf. Like cancelling a draft it is the manager's call, and a writer who
 * cannot do it is told why rather than shown nothing.
 */
export function ReverseRunAction({ order }: { order: ProductionOrder }) {
  const { t } = useTranslation("maker");
  const canManage = useCanManage("maker");
  const canWrite = useCanWrite("maker");
  const [asking, setAsking] = useState(false);
  const reverse = useReverseProduction();

  // Only a completed run posted anything to take back.
  if (order.status !== "COMPLETED" || (!canManage && !canWrite)) return null;

  const button = (
    <Button
      variant="outline"
      leftIcon={<Undo2 size={16} />}
      disabled={!canManage || reverse.isPending}
      onClick={() => setAsking(true)}
      data-testid="maker-detail-reverse-button"
    >
      {t("detail.reverse")}
    </Button>
  );

  return (
    <>
      {canManage ? (
        button
      ) : (
        <span title={t("detail.reverseNeedsManager")}>{button}</span>
      )}
      <ConfirmDialog
        open={asking}
        title={t("detail.reverseConfirm.title")}
        message={t("detail.reverseConfirm.description")}
        confirmLabel={t("detail.reverseConfirm.confirm")}
        cancelLabel={t("create.cancel")}
        variant="danger"
        onConfirm={() => {
          setAsking(false);
          reverse.mutate(order.id, {
            onSuccess: () => toast.success(t("detail.reverseSuccess")),
            // The refusal names why — what the run made has been used — in
            // the reader's language; the fallback is for a failure without
            // a sentence of its own.
            onError: (err) =>
              toast.error(extractApiError(err, t("detail.reverseFailed"))),
          });
        }}
        onCancel={() => setAsking(false)}
      />
    </>
  );
}
