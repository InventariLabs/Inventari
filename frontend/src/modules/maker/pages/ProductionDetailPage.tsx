import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate, useParams } from "react-router-dom";
import { Hammer, ExternalLink } from "lucide-react";
import { toast } from "sonner";
import { extractApiError, isNotFoundError } from "@/lib/errors";
import { useModulePageHeader } from "@/hooks/useModulePageHeader";
import { useCanManage, useCanWrite } from "@/hooks/useCanWrite";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { InlineQueryError, QueryError } from "@/components/ui/QueryResult";
import { RecordNotFound } from "@/components/ui/RecordNotFound";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { Textarea } from "@/components/ui/Textarea";
import { ProductionRunActions } from "@/modules/maker/components/ProductionRunActions";
import { RunPortions } from "@/modules/maker/components/RunPortions";
import { RunSteps } from "@/modules/maker/components/RunSteps";
import { OrderEditForm } from "@/modules/maker/components/OrderEditForm";
import { ProductionIngredientsTable } from "@/modules/maker/components/ProductionIngredientsTable";
import { RunCoverageCard } from "@/modules/maker/components/RunCoverageCard";
import { ProductionStockMovesTable } from "@/modules/maker/components/ProductionStockMovesTable";
import { ProductionOrderStats } from "@/modules/maker/components/ProductionOrderStats";
import { ShortageModal } from "@/modules/maker/components/ShortageModal";
import { CompleteRunDialog } from "@/modules/maker/components/CompleteRunDialog";
import { OutputBatchCard } from "@/modules/maker/components/OutputBatchCard";
import { RunAttachmentsSection } from "@/modules/maker/components/RunAttachmentsSection";
import { formatDecimalQty } from "@/utils/formatters";
import {
  useCancelProduction,
  useOrderStockMoves,
  useProductionOrder,
} from "@/modules/maker/hooks/useProduction";
import { useDuplicateOrderNavigation } from "@/modules/maker/hooks/useDuplicateOrderNavigation";
import { useCompleteRun } from "@/modules/maker/hooks/useCompleteRun";
import { usePlannedConsumption } from "@/modules/maker/hooks/usePlannedConsumption";
import { formatQuantityLocalized } from "@/lib/i18nHelpers";

/**
 * The run's stock movements. Reads its own list, so a failed read is said
 * beside the table that is missing rather than left looking like a run that
 * moved nothing.
 */
function OrderStockMoves({ orderId }: { orderId: string | undefined }) {
  const {
    data: stockMoves = [],
    isError,
    error,
    refetch,
  } = useOrderStockMoves(orderId);
  if (isError) {
    return <InlineQueryError error={error} onRetry={() => void refetch()} />;
  }
  if (stockMoves.length === 0) return null;
  return <ProductionStockMovesTable stockMoves={stockMoves} />;
}

export default function ProductionDetailPage() {
  const { t } = useTranslation("maker");
  const { orderId } = useParams<{ orderId: string }>();
  const navigate = useNavigate();
  const { setHeader } = useModulePageHeader();
  // Taking a run back is the manager's call — the same split the documents
  // module draws between executing a document and cancelling it. Edit,
  // Complete and Duplicate belong to the floor and stay with maker:write.
  const canManage = useCanManage("maker");
  const canWrite = useCanWrite("maker");

  const [showCancelConfirm, setShowCancelConfirm] = useState(false);
  const [cancelReason, setCancelReason] = useState("");
  const [isEditing, setIsEditing] = useState(false);

  const {
    data: order,
    isLoading,
    error,
    refetch,
  } = useProductionOrder(orderId);
  const {
    isPlanned,
    entries: plannedEntries,
    bomIsEmpty,
    shortages,
  } = usePlannedConsumption(order);
  const cancelMutation = useCancelProduction();
  const { duplicate, isDuplicating } = useDuplicateOrderNavigation();
  const completeRun = useCompleteRun(order);
  const {
    setShowConfirm: setShowCompleteConfirm,
    shortages: completeShortages,
    setShortages: setCompleteShortages,
    shortAtCreate,
    showShortage,
  } = completeRun;

  useEffect(() => {
    setHeader({
      // Name the run by what is being produced, not by a quantity: three screens
      // of the module would otherwise all be titled by their amount.
      title: order?.output_template_name ?? t("detail.title"),
      subtitle: order
        ? t("detail.plannedSummary", {
            qty: formatQuantityLocalized(
              t,
              order.planned_qty,
              order.output_uom_symbol,
            ),
          })
        : t("detail.subtitle"),
      backTo: "/maker/production",
    });
  }, [order, t, setHeader]);

  // An order that was cancelled away and a request that failed are two
  // different answers: "failed to load" over a deleted order sends the reader
  // looking for a fault that is not there.
  if (error && !isNotFoundError(error)) {
    return <QueryError error={error} onRetry={() => void refetch()} />;
  }

  if (isLoading) {
    return (
      <div className="flex flex-col items-center justify-center py-16">
        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-accent-600 mb-4" />
        <p className="text-on-muted font-medium uppercase tracking-widest text-[10px]">
          {t("detail.loading")}
        </p>
      </div>
    );
  }

  if (!order) {
    return (
      <RecordNotFound
        title={t("detail.notFound")}
        backTo="/maker/production"
        backLabel={t("detail.back")}
      />
    );
  }

  const isDraft = order.status === "DRAFT";
  const completedLines = order.lines ?? [];

  function handleCancel() {
    if (!order) return;
    cancelMutation.mutate(
      { orderId: order.id, reason: cancelReason.trim() || undefined },
      {
        onSuccess: () => {
          toast.success(
            t("detail.cancelSuccess", { defaultValue: "Production cancelled" }),
          );
          setCancelReason("");
        },
        onError: (err) => {
          toast.error(
            extractApiError(
              err,
              t("detail.cancelFailed", {
                defaultValue: "Failed to cancel production",
              }),
            ),
          );
        },
      },
    );
  }

  return (
    <div className="space-y-6 animate-in fade-in slide-in-from-bottom-4 duration-500">
      <div className="flex flex-wrap items-start justify-between gap-4">
        {/* The shell header already names the run by its output product, so
            repeating it here cost two of the first four lines on a phone.
            What is left is the identifier, shortened — the full value stays
            in the tooltip for anyone tracing a record. */}
        <div
          className="flex items-center gap-2 text-on-muted text-xs font-mono"
          title={order.number ?? order.id}
        >
          <Hammer size={14} />
          {order.number ?? order.id.slice(0, 8)}
        </div>
        <ProductionRunActions
          order={order}
          canManage={canManage}
          canWrite={canWrite}
          isDuplicating={isDuplicating}
          onEdit={() => setIsEditing((v) => !v)}
          onCancel={() => setShowCancelConfirm(true)}
          onComplete={() => setShowCompleteConfirm(true)}
          onDuplicate={() => duplicate(order.id)}
          onShortage={showShortage}
        />
      </div>

      {isEditing && isDraft ? (
        <OrderEditForm
          orderId={order.id}
          initial={{
            // The rest of the module shows quantities trimmed; the edit form
            // was the one place that opened on a raw "1.0000".
            planned_qty: formatDecimalQty(order.planned_qty),
            production_date: order.production_date,
            notes: order.notes,
          }}
          onDone={() => setIsEditing(false)}
        />
      ) : (
        <>
          <ProductionOrderStats order={order} />
          <OutputBatchCard order={order} />

          {order.notes && (
            <Card className="p-4">
              <div className="text-xs uppercase tracking-widest text-on-muted font-medium mb-2">
                {t("detail.card.notes", { defaultValue: "Notes" })}
              </div>
              <p className="text-sm text-on whitespace-pre-wrap">
                {order.notes}
              </p>
            </Card>
          )}
        </>
      )}

      {order.status === "IN_PROGRESS" && (
        <>
          <RunSteps order={order} canWrite={canWrite} />
          <RunPortions order={order} canWrite={canWrite} />
        </>
      )}

      <RunCoverageCard order={order} />

      <ProductionIngredientsTable
        lines={completedLines}
        planned={plannedEntries}
        isPlanned={isPlanned}
        shortages={shortages}
        shortageCount={order.shortage_count}
      />

      {order.cancel_reason && (
        <Card className="p-4 border-red-100 bg-red-50/50">
          <div className="text-xs uppercase tracking-widest text-on-muted font-medium mb-1">
            {t("detail.cancelReason", { defaultValue: "Cancel reason" })}
          </div>
          <p className="text-sm text-on whitespace-pre-wrap">
            {order.cancel_reason}
          </p>
        </Card>
      )}

      {order.produced_item_id && (
        <Card className="p-4 flex items-center justify-between gap-3">
          <div className="min-w-0">
            <div className="text-xs uppercase tracking-widest text-on-muted font-medium">
              {t("detail.producedItem", { defaultValue: "Produced item" })}
            </div>
            <p
              className="text-sm text-on-secondary mt-1 truncate"
              title={order.produced_item_id}
            >
              {order.produced_item_name ?? order.output_template_name ?? "—"}
            </p>
          </div>
          <Button
            variant="outline"
            size="sm"
            leftIcon={<ExternalLink size={14} />}
            // `/items/:id` is a redirect alias that lands on the list with the
            // item opened; address that destination directly.
            onClick={() =>
              navigate(
                `/inventory/items?open=${encodeURIComponent(order.produced_item_id!)}`,
              )
            }
            data-testid="maker-detail-produced-item-link"
          >
            {t("detail.viewProducedItem", { defaultValue: "View item" })}
          </Button>
        </Card>
      )}

      <OrderStockMoves orderId={orderId} />

      <RunAttachmentsSection orderId={order.id} />

      <CompleteRunDialog
        order={order}
        run={completeRun}
        bomIsEmpty={bomIsEmpty}
      />

      <ShortageModal
        open={completeShortages !== null}
        variant="danger"
        shortages={completeShortages ?? []}
        canConfirm={false}
        title={t("availability.completeShortage")}
        // Two different facts share one refusal: the run was born over stock
        // (the order recorded it), or the stock moved since. Saying the same
        // sentence for both sent readers looking for a theft of wax that
        // never happened.
        hint={
          shortAtCreate
            ? t("availability.completeShortageHintNever")
            : t("availability.completeShortageHint")
        }
        onCancel={() => setCompleteShortages(null)}
      />

      <ConfirmDialog
        open={showCancelConfirm}
        title={t("detail.cancelConfirm.title", {
          defaultValue: "Cancel production run?",
        })}
        message={
          order.status === "IN_PROGRESS"
            ? t("progress.cancelConfirm")
            : t("detail.cancelConfirm.description", {
                defaultValue:
                  "Cancelling marks this draft as cancelled. No stock will be moved.",
              })
        }
        confirmLabel={t("detail.cancelConfirm.confirm", {
          defaultValue: "Yes, cancel run",
        })}
        cancelLabel={t("create.cancel", { defaultValue: "Cancel" })}
        onConfirm={() => {
          setShowCancelConfirm(false);
          handleCancel();
        }}
        onCancel={() => {
          setShowCancelConfirm(false);
          setCancelReason("");
        }}
        variant="danger"
      >
        <Textarea
          aria-label={t("detail.cancelReasonPlaceholder", {
            defaultValue: "Cancellation reason",
          })}
          value={cancelReason}
          onChange={(e) => setCancelReason(e.target.value)}
          rows={2}
          className="w-full px-3 py-2 rounded-lg border border-border bg-surface-card text-sm text-on focus:outline-none focus:ring-2 focus:ring-primary-500/20 focus:border-primary-500"
          placeholder={t("detail.cancelReasonPlaceholder", {
            defaultValue: "Reason (optional)…",
          })}
          data-testid="maker-cancel-reason-input"
        />
      </ConfirmDialog>
    </div>
  );
}
