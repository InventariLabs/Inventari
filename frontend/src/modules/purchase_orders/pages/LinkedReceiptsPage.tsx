import { useEffect } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { Card } from "@/components/ui/Card";
import LoadingSpinner from "@/components/LoadingSpinner";
import { QueryError } from "@/components/ui/QueryResult";
import { RecordNotFound } from "@/components/ui/RecordNotFound";
import { isNotFoundError } from "@/lib/errors";
import { useModulePageHeader } from "@/hooks/useModulePageHeader";
import {
  usePurchaseOrder,
  useLinkedReceipts,
  usePendingQuantities,
} from "../hooks/usePurchaseOrders";
import { DocumentStatusBadge } from "@/modules/warehouse/moduleApi";
import { formatDate } from "@/utils/helpers";
import {
  formatPercentLocale,
  formatQuantityLocale,
  formatQuantityValue,
} from "@/utils/formatters";
import { unitLabel } from "@/lib/i18nHelpers";

export default function LinkedReceiptsPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { t } = useTranslation("purchase_orders");
  const { setHeader } = useModulePageHeader();

  const {
    data: po,
    isLoading: poLoading,
    isError: poFailed,
    error: poError,
    refetch: refetchPo,
  } = usePurchaseOrder(id ?? "");
  const {
    data: receipts = [],
    isLoading: receiptsLoading,
    isError: receiptsFailed,
    refetch: refetchReceipts,
  } = useLinkedReceipts(id ?? "");
  const pendingQuantities = usePendingQuantities(id ?? "", true);

  useEffect(() => {
    setHeader({
      backTo: `/purchase-orders/${id}`,
      title: t("linkedReceipts"),
    });
  }, [id, t, setHeader]);

  if (poLoading || receiptsLoading) return <LoadingSpinner />;

  // Without this branch a 500 fell through to `!po` below, and the reader was
  // told their order does not exist — a claim about their data where the
  // truth was about the server. The detail route of the same record has
  // answered this correctly all along.
  if (poFailed && !isNotFoundError(poError)) {
    return <QueryError onRetry={() => refetchPo()} />;
  }

  if (!po) {
    return (
      <RecordNotFound
        title={t("notFound")}
        backTo="/purchase-orders"
        backLabel={t("backToList")}
      />
    );
  }

  return (
    <div className="space-y-6">
      <Card className="p-5">
        <h2 className="text-sm font-medium text-on-secondary mb-4">
          {t("linkedReceipts")} — {po.number}
        </h2>
        {receiptsFailed ? (
          <QueryError onRetry={() => void refetchReceipts()} />
        ) : receipts.length > 0 ? (
          <div className="space-y-2">
            <div className="text-xs text-on-secondary mb-4">
              {t("receiptsNote")}
            </div>
            {receipts.map((receipt) => (
              <div
                key={receipt.id}
                className="flex items-center justify-between py-3 border-b border-border last:border-0 cursor-pointer hover:bg-surface-raised/50 rounded-lg px-2"
                onClick={() => navigate(`/warehouse/documents/${receipt.id}`)}
              >
                <div className="min-w-0 flex-1">
                  <div className="font-medium truncate">{receipt.number}</div>
                  <div className="text-xs text-on-secondary">
                    {formatDate(receipt.created_at)}
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  {/* These are warehouse documents, so they wear the document
 status badge — this printed the raw enum. */}
                  <DocumentStatusBadge status={receipt.status} />
                </div>
              </div>
            ))}
          </div>
        ) : (
          <div className="text-sm text-on-secondary">{t("noReceiptsYet")}</div>
        )}
      </Card>

      <Card className="p-5">
        <h2 className="text-sm font-medium text-on-secondary mb-4">
          {t("linesProgress")} — {po.number}
        </h2>
        <p className="text-xs text-on-secondary mb-4">
          {t("linesProgressHint")}
        </p>
        {po.lines
          .filter((l) => Number(l.quantity_ordered) > 0)
          .map((line) => {
            const inTransit = Number(pendingQuantities?.[line.id] ?? 0);
            const pct = Math.min(
              100,
              (Number(line.quantity_received) / Number(line.quantity_ordered)) *
                100,
            );
            return (
              <div
                key={line.id}
                className="flex items-center justify-between py-3 border-b border-border last:border-0"
              >
                <div className="min-w-0 flex-1">
                  <div className="font-medium truncate">{line.name}</div>
                  <div className="text-xs text-on-secondary">
                    {/* The wire's "0.000 / 2.000" is the column's scale, not
                        the reader's number: the shared formatter strips the
                        padding and writes the mark of the interface
                        language. */}
                    {t("receivedCompleted")}:{" "}
                    {formatQuantityLocale(line.quantity_received)} /{" "}
                    {formatQuantityLocale(line.quantity_ordered)}{" "}
                    {unitLabel(t, line.uom_symbol) || t("units")}
                    {inTransit > 0 && (
                      <span className="text-amber-600">
                        {" · "}
                        {t("receipt.colInTransit")}:{" "}
                        {formatQuantityValue(inTransit)}{" "}
                        {unitLabel(t, line.uom_symbol) || t("units")}
                      </span>
                    )}
                  </div>
                </div>
                <div className="w-32">
                  <div className="h-2 rounded-full bg-border overflow-hidden">
                    <div
                      className="h-full bg-accent-500 rounded-full transition-all"
                      style={{ width: `${pct}%` }}
                    />
                  </div>
                  <div className="text-xs text-right mt-1 text-on-secondary tabular-nums">
                    {formatPercentLocale(pct, 0)}
                  </div>
                </div>
              </div>
            );
          })}
      </Card>
    </div>
  );
}
