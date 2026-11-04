import { useState, useEffect, useCallback } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { downloadBlob } from "@/utils/helpers";
import { toast } from "sonner";
import LoadingSpinner from "@/components/LoadingSpinner";
import { Badge } from "@/components/ui/Badge";
import { STATUS_COLORS } from "@/modules/purchase_orders/lib/statusColors";
import { InlineQueryError, QueryError } from "@/components/ui/QueryResult";
import { RecordNotFound } from "@/components/ui/RecordNotFound";
import { isNotFoundError } from "@/lib/errors";
import { useModulePageHeader } from "@/hooks/useModulePageHeader";
import { useCanManage, useCanWrite } from "@/hooks/useCanWrite";
import { useHasPermission } from "@/module-sdk";
import { useModules } from "@/contexts/ModulesContext";
import { runWithToast } from "@/lib/api/runWithToast";
import {
  usePurchaseOrder,
  useLinkedReceipts,
  useConfirmPurchaseOrder,
  useCancelPurchaseOrder,
  useSendPoEmail,
  useDownloadPoPdf,
  useApprovePO,
  useRejectPO,
  useRequestPOApproval,
  usePOApprovalRequests,
  usePOApprovalWorkflowConfigured,
} from "../hooks/usePurchaseOrders";
import type { TargetApprovalRequest as ApprovalRequest } from "@/lib/moduleRegistry";
import { usePartner } from "@/hooks/usePartners";
import PurchaseOrderFormModal from "../components/PurchaseOrderFormModal";
import { POLinesCard } from "../components/POLinesCard";
import { POActionBar } from "../components/POActionBar";
import { POApprovalStatusCard } from "../components/POApprovalStatusCard";
import { PODetailsCard } from "../components/PODetailsCard";
import { POLinkedReceiptsCard } from "../components/POLinkedReceiptsCard";
import { toAmount } from "@/utils/formatters";
import { totalAmounts, type LineAmounts } from "@/utils/money";
import type { PurchaseOrder } from "../types/purchase-orders";
import {
  POActionDialogs,
  type POActionType,
} from "../components/POActionDialogs";

/** Read the server's ``viewer_can_decide`` off the latest request. */
function resolveViewerCanDecide(
  approval: { viewer_can_decide?: boolean | null } | null,
): boolean | null | undefined {
  return approval?.viewer_can_decide;
}

/**
 * The request to treat as the current one for the order. The requests
 * endpoint promises no date order, so the first match can be an older,
 * withdrawn request next to a newer one: newest is picked by `created_at`.
 */
function latestRequest(requests: ApprovalRequest[]): ApprovalRequest | null {
  if (requests.length === 0) return null;
  return (
    [...requests].sort(
      (a, b) =>
        new Date(b.created_at).getTime() - new Date(a.created_at).getTime(),
    )[0] ?? null
  );
}

/**
 * Where the order's approval request stands — a failed read is not "no
 * request found", which the header's actions act on, so the page says it
 * failed — read once for the header and
 * the approval card so the two cannot disagree. The card holds the decision
 * whenever it is on the page; the header then keeps to the order's own
 * actions.
 */
function approvalStateOf(
  requests: { items?: ApprovalRequest[] } | undefined,
  po: PurchaseOrder | undefined,
  approvalsEnabled: boolean,
) {
  const latestApproval = latestRequest(
    (requests?.items ?? []).filter((r) => r.target_id === po?.id),
  );
  return {
    latestApproval,
    hasPendingApproval:
      latestApproval?.status === "PENDING" ||
      latestApproval?.status === "IN_PROGRESS",
    viewerCanDecide: resolveViewerCanDecide(latestApproval),
    approvalCardShown: po?.status === "PENDING_APPROVAL" && approvalsEnabled,
  };
}

/**
 * What the order is worth, from the order.
 *
 * It already carries totals, computed by the same arithmetic that stores
 * them; this page used to recompute them in floats and disagreed by a cent
 * whenever a line's own tax landed on a half. The fallback is for an order
 * whose totals the API did not send; a ``null`` total is a line with no price,
 * and the card behind this says so instead of printing these.
 */
function orderTotals(po: PurchaseOrder): LineAmounts {
  const computed = totalAmounts(
    po.lines.map((l) => ({
      quantity: l.quantity_ordered,
      unit_price: l.unit_price,
      tax_rate: l.tax_rate,
    })),
  );
  return {
    net: toAmount(po.total_net) ?? computed.net,
    tax: toAmount(po.total_tax) ?? computed.tax,
    gross: toAmount(po.total_gross) ?? computed.gross,
  };
}

export default function PurchaseOrderDetailPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { t, i18n } = useTranslation(["purchase_orders", "common"]);
  const { setHeader } = useModulePageHeader();

  const [showEdit, setShowEdit] = useState(false);
  const [actionType, setActionType] = useState<POActionType>(null);
  // cancel restricted to admin/manager (backend enforces too).
  // The backend checks purchase_orders:manage; asking for role names
  // instead refused a custom role holding the key (AGENTS.md: gate on a
  // permission, never on a role name).
  const canManage = useCanManage("purchase_orders");
  const canWrite = useCanWrite("purchase_orders");
  // Approve/Reject answer to `approvals:approve`, not to manage: the bar was
  // offering them on the wrong key in both directions.
  const canDecide = useHasPermission("approvals:approve");
  const { isModuleEnabled } = useModules();

  const {
    data: po,
    isLoading,
    isError,
    error,
    refetch,
  } = usePurchaseOrder(id ?? "");
  // Which actions make sense on a parked order depends on whether a request
  // is still waiting for a decision. The header and the approval
  // slot read the same requests list, so both agree on what is pending
  //.
  const requestsQuery = usePOApprovalRequests();
  // The header's request action hangs on the same one bit the approval slot
  // does: whether the engine would take the request. Sourced from the
  // server, not the workflow list — the role composing the request holds
  // the module's write right and no read grant over approvals, so the list
  // answers it nothing.
  const workflowConfigured = usePOApprovalWorkflowConfigured();
  const confirmMutation = useConfirmPurchaseOrder();
  const cancelMutation = useCancelPurchaseOrder();
  const sendEmailMutation = useSendPoEmail();
  const downloadPdfMutation = useDownloadPoPdf();
  const approvePOMutation = useApprovePO();
  const rejectPOMutation = useRejectPO();
  const requestApprovalMutation = useRequestPOApproval();

  const {
    data: linkedReceipts = [],
    isLoading: receiptsLoading,
    isError: receiptsFailed,
    refetch: refetchReceipts,
  } = useLinkedReceipts(id ?? "");

  // the order carries its supplier's name, so display it from there.
  // Searching the active-partner page for it rendered a raw UUID as soon as
  // the supplier was deactivated or fell past the page size — and the e-mail
  // dialog lost the address in the same cases, which is why the partner is
  // fetched by id instead.
  const partnerName = po?.partner_id
    ? (po.partner_name ?? po.partner_id)
    : null;
  const { data: partner } = usePartner(po?.partner_id ?? null);

  const approvalsEnabled = isModuleEnabled("approvals");
  const {
    latestApproval,
    hasPendingApproval,
    viewerCanDecide,
    approvalCardShown,
  } = approvalStateOf(requestsQuery.data, po, approvalsEnabled);

  const downloadPdf = downloadPdfMutation.mutateAsync;
  const handleDownloadPdf = useCallback(async () => {
    if (!po) return;
    const blob = await runWithToast(
      () => downloadPdf({ poId: po.id, lang: i18n.language }),
      { errorFallback: t("unknownError") },
    );
    if (blob) {
      downloadBlob(blob, `PO_${po.number.replace(/\//g, "-")}.pdf`);
    }
  }, [po, downloadPdf, i18n.language, t]);
  const openEdit = useCallback(() => setShowEdit(true), []);
  // The order's open lines are taken in on the receive screen in one press;
  // it comes back here when the reader asks.
  const openReceive = useCallback(() => {
    if (!po) return;
    navigate(`/warehouse/receive?order=${po.id}`, {
      state: { backTo: `/purchase-orders/${po.id}` },
    });
  }, [navigate, po]);
  const pdfPending = downloadPdfMutation.isPending;

  useEffect(() => {
    setHeader({
      backTo: "/purchase-orders",
      title: po ? po.number : t("title"),
      subtitle: partnerName ?? undefined,
      // Inline with the number, the way the document detail shows it — here it
      // sat on its own line under the title.
      statusBadge: po ? (
        <Badge variant={STATUS_COLORS[po.status] ?? "default"}>
          {t(`status.${po.status}`)}
        </Badge>
      ) : undefined,
      // On the line of the number, as on the document detail. They used to
      // stand in a row of their own under the title.
      actions: po ? (
        <POActionBar
          po={po}
          canManage={canManage}
          canDecide={canDecide}
          canWrite={canWrite}
          approvalsEnabled={approvalsEnabled}
          workflowConfigured={workflowConfigured}
          hasPendingApproval={hasPendingApproval}
          approvalCardShown={approvalCardShown}
          viewer_can_decide={viewerCanDecide}
          pdfPending={pdfPending}
          onEdit={openEdit}
          onAction={setActionType}
          onDownloadPdf={() => void handleDownloadPdf()}
          onReceive={openReceive}
        />
      ) : undefined,
    });
  }, [
    po,
    t,
    setHeader,
    partnerName,
    canManage,
    canDecide,
    canWrite,
    approvalsEnabled,
    workflowConfigured,
    hasPendingApproval,
    approvalCardShown,
    viewerCanDecide,
    pdfPending,
    openEdit,
    openReceive,
    handleDownloadPdf,
  ]);

  const handleConfirm = async () => {
    if (!po) return;
    await runWithToast(
      async () => {
        const updated = await confirmMutation.mutateAsync(po.id);
        toast.success(
          updated.status === "PENDING_APPROVAL"
            ? t("sentForApproval")
            : t("confirmSuccess"),
        );
      },
      { errorFallback: t("unknownError") },
    );
    setActionType(null);
  };

  const handleCancel = async () => {
    if (!po) return;
    await runWithToast(() => cancelMutation.mutateAsync(po.id), {
      success: t("cancelSuccess"),
      errorFallback: t("unknownError"),
    });
    setActionType(null);
  };

  const handleSendEmail = async () => {
    if (!po) return;
    // The supplier reads this e-mail; send it in the language the user is
    // working in rather than the hardcoded English default.
    await runWithToast(
      () => sendEmailMutation.mutateAsync({ poId: po.id, lang: i18n.language }),
      {
        success: t("emailSent"),
        errorFallback: t("unknownError"),
      },
    );
    setActionType(null);
  };

  // ── Approval actions ─────────
  const handleApprove = async () => {
    if (!po) return;
    await runWithToast(() => approvePOMutation.mutateAsync({ poId: po.id }), {
      success: t("approveSuccess"),
      errorFallback: t("unknownError"),
    });
    setActionType(null);
  };

  const handleReject = async (reason: string) => {
    if (!po) return;
    await runWithToast(
      () => rejectPOMutation.mutateAsync({ poId: po.id, notes: reason }),
      {
        success: t("rejectSuccess"),
        errorFallback: t("unknownError"),
      },
    );
    setActionType(null);
  };

  const handleRequestApproval = async () => {
    if (!po) return;
    await runWithToast(() => requestApprovalMutation.mutateAsync(po.id), {
      success: t("requestApprovalSuccess"),
      errorFallback: t("unknownError"),
    });
    setActionType(null);
  };

  const handleDialogConfirm = () => {
    switch (actionType) {
      case "confirm":
        return handleConfirm();
      case "cancel":
        return handleCancel();
      case "approve":
        return handleApprove();
      case "requestApproval":
        return handleRequestApproval();
      case "send":
        return handleSendEmail();
      default:
        return undefined;
    }
  };

  if (isLoading) return <LoadingSpinner />;
  if (isError && !isNotFoundError(error)) {
    // "This order does not exist" is a different sentence from "we could not
    // load it" — and only the second one is worth retrying.
    return <QueryError onRetry={() => void refetch()} />;
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

  const { net: poNet, tax: poTax, gross: poTotal } = orderTotals(po);

  return (
    <div className="space-y-6">
      {requestsQuery.isError && approvalsEnabled && (
        <InlineQueryError
          error={requestsQuery.error}
          onRetry={() => void requestsQuery.refetch()}
        />
      )}
      {approvalCardShown && (
        <POApprovalStatusCard
          po={po}
          onApprove={async (_requestId, notes) => {
            await approvePOMutation.mutateAsync({ poId: po.id, notes });
          }}
          onRequest={async () => {
            await requestApprovalMutation.mutateAsync(po.id);
          }}
          onReject={async (_requestId, notes) => {
            await rejectPOMutation.mutateAsync({ poId: po.id, notes });
          }}
        />
      )}

      {/* the 2-column grid never got a second child — one column
          lets the details card span the page like the sections below. */}
      <div className="grid grid-cols-1 gap-6">
        <PODetailsCard
          po={po}
          partnerName={partnerName}
          approval={latestApproval}
        />
      </div>

      <POLinesCard
        lines={po.lines}
        poNet={poNet}
        poTax={poTax}
        poTotal={poTotal}
        totalKnown={po.total_gross !== null}
        currency={po.currency}
        locale={i18n.language}
        status={po.status}
        t={t}
      />

      <POLinkedReceiptsCard
        poId={po.id}
        receiptCount={linkedReceipts.length}
        isLoading={receiptsLoading}
        isError={receiptsFailed}
        onRetry={() => void refetchReceipts()}
      />

      {showEdit && (
        <PurchaseOrderFormModal
          purchaseOrder={po}
          onClose={() => setShowEdit(false)}
          onSuccess={() => setShowEdit(false)}
        />
      )}

      <POActionDialogs
        po={po}
        actionType={actionType}
        partnerEmail={partner?.email ?? null}
        onConfirm={handleDialogConfirm}
        onCancel={() => setActionType(null)}
        onReject={handleReject}
      />
    </div>
  );
}
