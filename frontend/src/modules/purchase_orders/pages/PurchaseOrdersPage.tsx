import { useCallback, useDeferredValue, useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { FileText, Plus } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/Button";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { EmptyState } from "@/components/ui/EmptyState";
import { ListControlBar } from "@/components/ui/ListControlBar";
import { Pagination } from "@/module-sdk";
import LoadingSpinner from "@/components/LoadingSpinner";
import { QueryError } from "@/components/ui/QueryResult";
import { useModulePageHeader } from "@/hooks/useModulePageHeader";
import { useCanManage, useCanWrite } from "@/hooks/useCanWrite";
import { ReadOnlyNotice } from "@/components/ui/ReadOnlyNotice";
import { PartnerFilterBanner } from "@/modules/partners/moduleApi";
import { extractApiError } from "@/lib/errors";
import PurchaseOrderFormModal from "@/modules/purchase_orders/components/PurchaseOrderFormModal";
import { PurchaseOrderList } from "@/modules/purchase_orders/components/PurchaseOrderList";
import {
  useCancelPurchaseOrder,
  useConfirmPurchaseOrder,
  usePurchaseOrder,
  usePurchaseOrders,
} from "@/modules/purchase_orders/hooks/usePurchaseOrders";
import { usePOConfirmMessage } from "@/modules/purchase_orders/hooks/usePOConfirmMessage";
import type {
  POStatus,
  PurchaseOrder,
  PurchaseOrderRow,
} from "@/modules/purchase_orders/types/purchase-orders";

const PAGE_SIZE = 50;
const STATUS_FILTERS: Array<"ALL" | POStatus> = [
  "ALL",
  "DRAFT",
  "PENDING_APPROVAL",
  "CONFIRMED",
  "COMPLETED",
  "CANCELLED",
];

/**
 * The order with this id, once it has arrived; null for no id or before.
 * A read that failed is handed to `onFailed`, so the press that asked for
 * it says so instead of doing nothing.
 */
function useOrderOnce(
  id: string | null,
  onFailed: (error: unknown) => void,
): PurchaseOrder | null {
  const { data, isError, error } = usePurchaseOrder(id ?? "");
  useEffect(() => {
    if (id !== null && isError) onFailed(error);
  }, [id, isError, error, onFailed]);
  return id !== null && data?.id === id ? data : null;
}

export default function PurchaseOrdersPage() {
  const { t } = useTranslation(["purchase_orders", "common"]);
  const navigate = useNavigate();
  const { setHeader } = useModulePageHeader();
  const canWrite = useCanWrite("purchase_orders");
  const canManage = useCanManage("purchase_orders");
  const [showCreate, setShowCreate] = useState(false);
  // A list row carries no lines; editing and confirming read the whole
  // order — the form edits its lines, and whether confirming needs an
  // approval depends on whether every line has a price.
  const [editingId, setEditingId] = useState<string | null>(null);
  const editFailed = useCallback(
    (error: unknown) => {
      toast.error(extractApiError(error, t("unknownError")));
      setEditingId(null);
    },
    [t],
  );
  const editingPO = useOrderOnce(editingId, editFailed);
  const [actionId, setActionId] = useState<string | null>(null);
  const actionFailed = useCallback(
    (error: unknown) => {
      toast.error(extractApiError(error, t("unknownError")));
      setActionId(null);
      setActionType(null);
    },
    [t],
  );
  const actionPO = useOrderOnce(actionId, actionFailed);
  const [actionType, setActionType] = useState<"confirm" | "cancel" | null>(
    null,
  );
  // Same reading as the detail page's dialog, from the same hook: the
  // approval flag is not the whole answer, so neither screen may hand the
  // reader a condition it has already resolved for them.
  const confirmMessage = usePOConfirmMessage(actionPO);
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState<"ALL" | POStatus>("ALL");
  const [offset, setOffset] = useState(0);
  const deferredSearch = useDeferredValue(search.trim());

  useEffect(() => {
    setHeader({
      title: t("title"),
      actions: canWrite ? (
        <Button
          variant="primary"
          leftIcon={<Plus size={16} />}
          onClick={() => setShowCreate(true)}
        >
          {t("createOrder")}
        </Button>
      ) : undefined,
    });
  }, [t, setHeader, canWrite]);

  // reached from a partner card as ?partner_id=…, so the filter lives
  // in the URL and survives a reload.
  const [searchParams, setSearchParams] = useSearchParams();
  const partnerId = searchParams.get("partner_id");
  const clearPartnerFilter = () => {
    const next = new URLSearchParams(searchParams);
    next.delete("partner_id");
    setSearchParams(next, { replace: true });
  };

  const { data, isLoading, isError, refetch } = usePurchaseOrders({
    search: deferredSearch || undefined,
    status: statusFilter === "ALL" ? undefined : statusFilter,
    partner_id: partnerId ?? undefined,
    limit: PAGE_SIZE,
    offset,
  });
  const purchaseOrders = data?.items ?? [];
  const total = data?.total ?? 0;
  const confirmMutation = useConfirmPurchaseOrder();
  const cancelMutation = useCancelPurchaseOrder();

  const handleSearchChange = (value: string) => {
    setSearch(value);
    setOffset(0);
  };

  const handleStatusChange = (value: string) => {
    setStatusFilter(value as "ALL" | POStatus);
    setOffset(0);
  };

  const handleAction = (po: PurchaseOrderRow, type: "confirm" | "cancel") => {
    setActionId(po.id);
    setActionType(type);
  };

  const confirmAction = async () => {
    if (!actionPO || !actionType) return;
    try {
      if (actionType === "confirm") {
        const updated = await confirmMutation.mutateAsync(actionPO.id);
        toast.success(
          updated.status === "PENDING_APPROVAL"
            ? t("sentForApproval")
            : t("confirmSuccess"),
        );
      } else {
        await cancelMutation.mutateAsync(actionPO.id);
        toast.success(t("cancelSuccess"));
      }
    } catch (err) {
      toast.error(extractApiError(err, t("unknownError")));
    } finally {
      setActionId(null);
      setActionType(null);
    }
  };

  const hasFilters = Boolean(search || statusFilter !== "ALL");

  return (
    <div className="space-y-6">
      <ReadOnlyNotice module="purchase_orders" />
      <ListControlBar
        search={{
          value: search,
          onChange: handleSearchChange,
          placeholder: t("searchPlaceholder"),
        }}
        primaryTabs={{
          value: statusFilter,
          onChange: handleStatusChange,
          options: STATUS_FILTERS.map((status) => ({
            value: status,
            label: status === "ALL" ? t("statusAll") : t(`status.${status}`),
          })),
        }}
        resultCount={isError ? undefined : total}
      />

      <PartnerFilterBanner
        partnerId={partnerId}
        label={(name) => t("filters.partnerFilter", { name })}
        onClear={clearPartnerFilter}
      />

      {isLoading && !data ? (
        <LoadingSpinner />
      ) : isError ? (
        /* A failed request used to render the "no orders yet" card, which
           invites the reader to create an order they may already have
. */
        <QueryError onRetry={() => void refetch()} />
      ) : purchaseOrders.length === 0 ? (
        <PurchaseOrdersEmptyState
          hasFilters={hasFilters}
          canWrite={canWrite}
          onCreate={() => setShowCreate(true)}
        />
      ) : (
        <PurchaseOrderList
          purchaseOrders={purchaseOrders}
          canWrite={canWrite}
          canManage={canManage}
          onView={(po) => navigate(`/purchase-orders/${po.id}`)}
          onEdit={(po) => setEditingId(po.id)}
          onConfirm={(po) => handleAction(po, "confirm")}
          onCancel={(po) => handleAction(po, "cancel")}
        />
      )}

      {total > PAGE_SIZE && (
        <Pagination
          skip={offset}
          limit={PAGE_SIZE}
          total={total}
          onPrev={() =>
            setOffset((current) => Math.max(0, current - PAGE_SIZE))
          }
          onNext={() => setOffset((current) => current + PAGE_SIZE)}
        />
      )}

      {showCreate && (
        <PurchaseOrderFormModal
          onClose={() => setShowCreate(false)}
          onSuccess={() => setShowCreate(false)}
        />
      )}

      {editingPO && (
        <PurchaseOrderFormModal
          purchaseOrder={editingPO}
          onClose={() => setEditingId(null)}
          onSuccess={() => setEditingId(null)}
        />
      )}

      <ConfirmDialog
        open={actionType !== null && actionPO !== null}
        title={
          actionType === "confirm"
            ? t("confirmOrder", { number: actionPO?.number })
            : t("cancelOrder", { number: actionPO?.number })
        }
        message={
          actionType === "confirm"
            ? confirmMessage
            : t("cancelOrderDescription")
        }
        variant={actionType === "cancel" ? "danger" : "default"}
        confirmLabel={
          actionType === "confirm" ? t("confirm") : t("cancelOrderAction")
        }
        cancelLabel={t("common:form.cancel")}
        onConfirm={confirmAction}
        onCancel={() => {
          setActionId(null);
          setActionType(null);
        }}
      />
    </div>
  );
}

/**
 * Empty state for the orders list. Extracted from `PurchaseOrdersPage` so the
 * filtered/empty branch logic does not push the page over the `complexity`
 * gate (§4, `eslint.config.js`).
 */
function PurchaseOrdersEmptyState({
  hasFilters,
  canWrite,
  onCreate,
}: {
  hasFilters: boolean;
  canWrite: boolean;
  onCreate: () => void;
}) {
  const { t } = useTranslation(["purchase_orders", "common"]);
  return (
    <EmptyState
      icon={FileText}
      title={hasFilters ? t("emptyFilteredTitle") : t("noOrders")}
      description={
        hasFilters
          ? t("emptyFilteredDescription")
          : canWrite
            ? t("noOrdersDescription")
            : t("noOrdersDescriptionReadOnly")
      }
      primaryAction={
        !hasFilters && canWrite ? (
          <Button
            variant="primary"
            leftIcon={<Plus size={16} />}
            onClick={onCreate}
          >
            {t("createOrder")}
          </Button>
        ) : undefined
      }
    />
  );
}
