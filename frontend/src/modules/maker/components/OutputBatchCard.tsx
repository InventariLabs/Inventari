import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import { ClipboardList, Pause, Play, Printer } from "lucide-react";
import { toast } from "sonner";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { Textarea } from "@/components/ui/Textarea";
import { useCanManage } from "@/hooks/useCanWrite";
import { extractApiError } from "@/lib/errors";
import { formatDate } from "@/utils/formatters";
import { BarcodeLabelSheet } from "@/modules/shared/components/BarcodeLabelSheet";
import { useOutputBatchStatus } from "@/modules/maker/hooks/useBatches";
import { useIsHomeProfile } from "@/modules/maker/hooks/useIsHomeProfile";
import { runBatches } from "@/modules/maker/lib/runBatches";
import type { ProductionOrder } from "@/modules/maker/types/maker";

/** Batch labels a run offers to print: one per unit it made, within the
 *  printing module's two hundred. */
const MAX_LABELS = 200;

/** One label per unit made: a run of twelve jars prints twelve. The sheet
 *  asks for the copies of every batch, so a run in several batches starts
 *  from its units spread over them. */
export function labelsForRun(order: ProductionOrder): number {
  const made = Number(order.actual_qty ?? order.planned_qty);
  if (!Number.isFinite(made) || made <= 0) return 1;
  const batches = Math.max(1, runBatches(order).length);
  return Math.min(MAX_LABELS, Math.max(1, Math.ceil(made / batches)));
}

const HELD = new Set(["quarantined", "held"]);

function StatusNote({ status }: { status: string | null | undefined }) {
  const { t } = useTranslation("maker");
  if (!status || status === "active") return null;
  if (HELD.has(status))
    return <Badge variant="warning">{t("batches.card.onHold")}</Badge>;
  if (status === "expired")
    return <Badge variant="danger">{t("batches.card.expired")}</Badge>;
  return <Badge variant="danger">{t("batches.card.recalled")}</Badge>;
}

/**
 * The batch a completed run filed its output under: the code, the day it was
 * made and until when it keeps, and what can be done with it — print its
 * labels, open its batch record, put it on hold and release it.
 *
 * At home the card speaks of jars and their best-before; the batch code is
 * still shown, small, but nothing asks the reader to manage it.
 */
export function OutputBatchCard({ order }: { order: ProductionOrder }) {
  const { t } = useTranslation("maker");
  const navigate = useNavigate();
  const home = useIsHomeProfile();
  const canManage = useCanManage("maker");
  const { hold, release } = useOutputBatchStatus(order.id);
  const [printing, setPrinting] = useState<string | null>(null);
  const [asking, setAsking] = useState(false);
  const [reason, setReason] = useState("");
  const batches = runBatches(order);
  if (batches.length === 0) return null;
  const several = batches.length > 1;
  const anyHeld = batches.some((batch) => HELD.has(batch.status));
  const allHeld = batches.every((batch) => HELD.has(batch.status));

  function putOnHold() {
    hold.mutate(reason.trim(), {
      onSuccess: () => {
        toast.success(t("batches.card.heldToast"));
        setReason("");
      },
      onError: (err) =>
        toast.error(extractApiError(err, t("batches.card.holdFailed"))),
    });
  }

  function releaseBatch() {
    release.mutate(undefined, {
      onSuccess: () => toast.success(t("batches.card.releasedToast")),
      onError: (err) =>
        toast.error(extractApiError(err, t("batches.card.holdFailed"))),
    });
  }

  return (
    <Card className="p-4 space-y-3" data-testid="maker-output-batch-card">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 space-y-1">
          <h2 className="text-xs uppercase tracking-widest text-on-muted font-medium">
            {home ? t("batches.card.titleHome") : t("batches.card.title")}
          </h2>
          {!several && (
            <p
              className={
                home
                  ? "text-xs text-on-muted font-mono"
                  : "text-base text-on font-semibold font-mono"
              }
              data-testid="maker-output-batch-code"
            >
              {home
                ? t("batches.card.codeHome", { code: batches[0].lot_name })
                : batches[0].lot_name}
            </p>
          )}
          <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-sm">
            <dt className="text-on-muted">{t("batches.card.madeOn")}</dt>
            <dd className="text-on">
              {order.production_date ? formatDate(order.production_date) : "—"}
            </dd>
            {!several && (
              <>
                <dt className="text-on-muted">
                  {t("batches.bestBeforeLabel")}
                </dt>
                <dd className="text-on" data-testid="maker-output-best-before">
                  {batches[0].best_before
                    ? formatDate(batches[0].best_before)
                    : "—"}
                </dd>
              </>
            )}
          </dl>
          {several && (
            <ul
              className="space-y-1 text-sm"
              data-testid="maker-output-batches"
            >
              {batches.map((batch) => (
                <li
                  key={batch.lot_id}
                  className="flex flex-wrap items-center gap-x-3 gap-y-1"
                >
                  <span className="font-mono text-on">{batch.lot_name}</span>
                  <span className="text-on-muted">
                    {t("batches.bestBeforeLabel")}:{" "}
                    {batch.best_before ? formatDate(batch.best_before) : "—"}
                  </span>
                  <StatusNote status={batch.status} />
                  <Button
                    variant="ghost"
                    size="sm"
                    aria-label={`${t("batches.card.printLabels")}: ${batch.lot_name}`}
                    title={`${t("batches.card.printLabels")}: ${batch.lot_name}`}
                    onClick={() => setPrinting(batch.lot_id)}
                    data-testid="maker-print-batch-labels"
                  >
                    <Printer size={16} />
                  </Button>
                </li>
              ))}
            </ul>
          )}
        </div>
        {!several && <StatusNote status={batches[0].status} />}
      </div>
      <div className="flex flex-wrap gap-2">
        {!several && (
          <Button
            variant="outline"
            size="sm"
            leftIcon={<Printer size={16} />}
            onClick={() => setPrinting(batches[0].lot_id)}
            data-testid="maker-print-batch-labels"
          >
            {home
              ? t("batches.card.printJarLabels")
              : t("batches.card.printLabels")}
          </Button>
        )}
        <Button
          variant="outline"
          size="sm"
          leftIcon={<ClipboardList size={16} />}
          onClick={() => navigate(`/maker/production/${order.id}/record`)}
          data-testid="maker-open-batch-record"
        >
          {t("batches.card.record")}
        </Button>
        {canManage && !allHeld && (
          <Button
            variant="outline"
            size="sm"
            leftIcon={<Pause size={16} />}
            onClick={() => setAsking(true)}
            disabled={hold.isPending}
            data-testid="maker-hold-batch"
          >
            {t("batches.card.hold")}
          </Button>
        )}
        {canManage && anyHeld && (
          <Button
            variant="outline"
            size="sm"
            leftIcon={<Play size={16} />}
            onClick={releaseBatch}
            isLoading={release.isPending}
            data-testid="maker-release-batch"
          >
            {t("batches.card.release")}
          </Button>
        )}
      </div>
      {printing && (
        <BarcodeLabelSheet
          target={{ lotIds: [printing] }}
          initialCopies={labelsForRun(order)}
          title={home ? t("batches.card.jarLabelsTitle") : undefined}
          onClose={() => setPrinting(null)}
        />
      )}
      <ConfirmDialog
        open={asking}
        title={t("batches.card.holdTitle")}
        message={t("batches.card.holdMessage")}
        confirmLabel={t("batches.card.hold")}
        cancelLabel={t("create.cancel")}
        confirmDisabled={reason.trim() === ""}
        onConfirm={() => {
          setAsking(false);
          putOnHold();
        }}
        onCancel={() => {
          setAsking(false);
          setReason("");
        }}
        variant="default"
      >
        <Textarea
          label={t("batches.card.holdReason")}
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          rows={2}
          required
          data-testid="maker-hold-reason"
        />
      </ConfirmDialog>
    </Card>
  );
}
