import { useState, useEffect } from "react";
import { useTranslation } from "react-i18next";
import type { TFunction } from "i18next";
import { Link, useSearchParams } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import {
  User as UserIcon,
  Coins,
  ListOrdered,
  ExternalLink,
  Barcode,
  SearchX,
} from "lucide-react";

import { Card, CardContent } from "@/components/ui/Card";
import { buttonVariants } from "@/components/ui/Button";
import { ListControlBar } from "@/components/ui/ListControlBar";
import Pagination from "@/components/ui/Pagination";
import { QueryError } from "@/components/ui/QueryResult";
import { DynamicIcon } from "@/components/ui/DynamicIcon";
import { queryKeys } from "@/hooks/queries/keys";
import { invalidation } from "@/lib/api/invalidation";
import { useModulePageHeader } from "@/hooks/useModulePageHeader";
import { useHasPermission } from "@/hooks/useHasPermission";
import { useDocumentCurrency } from "@/hooks/useDocumentCurrency";
import { useApprovalRequests } from "@/modules/approvals/hooks/useApprovalRequests";
import { useCanDecideApprovals } from "@/modules/approvals/hooks/useApprovalPermissions";
import { ApprovalBadge } from "@/modules/approvals/components/ApprovalBadge";
import { ApprovalStageStepper } from "@/modules/approvals/components/ApprovalStageStepper";
import { ApprovalDecisionPanel } from "@/modules/approvals/components/ApprovalDecisionPanel";
import {
  targetDecisionApi,
  type ApprovalRequest,
} from "@/modules/approvals/api/approvals";
import { OPEN_APPROVAL_STATES } from "@/modules/approvals/approvalStates";
import { targetPath } from "@/modules/approvals/targetTypes";
import { formatMoney, formatDate } from "@/utils/formatters";
import { cn } from "@/lib/utils";

// This is a decision queue, so it opens on the states that still need
// a decision. Deleting a document cancels its request, and a cancelled
// request has nothing left to decide — those belong under an explicit tab,
// not in the default view.
const OPEN_STATES = OPEN_APPROVAL_STATES;

const STATUS_TABS: { value: string; key: string }[] = [
  { value: OPEN_STATES, key: "dashboard.tabs.waiting" },
  { value: "APPROVED", key: "dashboard.tabs.approved" },
  { value: "REJECTED", key: "dashboard.tabs.rejected" },
  { value: "CANCELLED", key: "dashboard.tabs.cancelled" },
  { value: "", key: "dashboard.tabs.all" },
];

// Target type label keys — looked up via t() at render time so the
// labels follow the user's locale instead of being hardcoded English.
const TARGET_TYPE_KEYS: Record<string, string> = {
  document: "dashboard.targetTypes.document",
  equipment_checkout: "dashboard.targetTypes.equipmentCheckout",
  purchase_order: "dashboard.targetTypes.purchaseOrder",
};

// What the link to a request's target is called. Without one per target type
// the card offered a way through to documents only, so a purchase order was a
// dead end on the screen meant to decide about it. A target type missing from
// `targetPath` simply gets no link.
const TARGET_LINK_LABELS: Record<string, string> = {
  document: "dashboard.viewDocument",
  purchase_order: "dashboard.viewPurchaseOrder",
  equipment_checkout: "dashboard.viewEquipment",
};

/** The empty state's title for the tab that is open: "no requests are waiting"
 * is only true of the tab that lists the waiting ones. */
function emptyTitle(
  t: TFunction<"approvals">,
  statusFilter: string,
  canDecide: boolean,
): string {
  switch (statusFilter) {
    case "APPROVED":
      return t("dashboard.emptyApproved");
    case "REJECTED":
      return t("dashboard.emptyRejected");
    case "CANCELLED":
      return t("dashboard.emptyCancelled");
    case "":
      return t("dashboard.emptyAll");
    default:
      return canDecide ? t("dashboard.empty") : t("dashboard.emptyNoDecide");
  }
}

// ~300px per RequestCard; 100 cards made the page ~31k px tall.
const PAGE_SIZE = 20;

export default function ApprovalsDashboard() {
  const { t } = useTranslation("approvals");
  const { setHeader } = useModulePageHeader();
  // The tab lives in the address: a notification or a link from a purchase
  // order or a document names the tab it is about, and React Router swaps the
  // search string without unmounting this route, so the tab is read on every
  // render instead of once at mount. The value has to name a tab: an arbitrary
  // string would render a control bar with nothing selected.
  const [searchParams, setSearchParams] = useSearchParams();
  const requestedStatus = searchParams.get("status");
  const statusFilter = STATUS_TABS.some((tab) => tab.value === requestedStatus)
    ? (requestedStatus as string)
    : OPEN_STATES;
  const selectStatus = (value: string) => {
    const next = new URLSearchParams(searchParams);
    if (value === OPEN_STATES) next.delete("status");
    else next.set("status", value);
    setSearchParams(next, { replace: true });
  };
  const [search, setSearch] = useState("");
  const [offset, setOffset] = useState(0);

  useEffect(() => {
    setHeader({
      title: t("approvals:dashboard.title"),
      subtitle: t("approvals:dashboard.subtitle"),
    });
  }, [t, setHeader]);

  // Reset pagination whenever the status tab or the search text changes.
  useEffect(() => {
    setOffset(0);
  }, [statusFilter, search]);

  const canDecide = useCanDecideApprovals();
  // The settings screen behind the link below is administrator-only
  // (settingsAccess), so the link shows only to those it lets in.
  const isAdmin = useHasPermission("admin:access");
  const { data, isLoading, isError, refetch } = useApprovalRequests({
    status: statusFilter || undefined,
    search: search.trim() || undefined,
    offset,
    limit: PAGE_SIZE,
  });

  const requests = data?.items ?? [];
  const total = data?.total ?? 0;

  return (
    <div className="space-y-6">
      {/* The self-approval escape hatch lives under this module's settings
          screen, which nothing in the app linked to — an organization whose
          workflow could only be saved by it had no way to arrive. */}
      {isAdmin && (
        <div className="flex justify-end">
          <Link
            to="/settings/modules/approvals"
            className="inline-flex items-center gap-1 text-sm text-on-secondary underline hover:text-on"
          >
            <ExternalLink size={14} />
            {t("common:settings.moduleSettings.open")}
          </Link>
        </div>
      )}
      <ListControlBar
        search={{
          value: search,
          onChange: setSearch,
          placeholder: t("dashboard.searchPlaceholder"),
        }}
        primaryTabs={{
          value: statusFilter,
          onChange: (value) => selectStatus(value as string),
          options: STATUS_TABS.map((tab) => ({
            value: tab.value,
            label: t(tab.key),
          })),
        }}
      />

      {isLoading ? (
        <div className="flex items-center justify-center py-12">
          <p className="text-on-muted">{t("common:messages.loading")}</p>
        </div>
      ) : isError ? (
        /* "Nothing to approve" and "we could not reach the server" are not the
 same message to give someone waiting on a decision. */
        <QueryError onRetry={() => void refetch()} />
      ) : requests.length === 0 ? (
        <QueueEmptyState
          canDecide={canDecide}
          search={search.trim()}
          statusFilter={statusFilter}
        />
      ) : (
        <div className="space-y-3">
          {requests.map((request) => (
            <RequestCard key={request.id} request={request} />
          ))}
        </div>
      )}

      <Pagination
        skip={offset}
        limit={PAGE_SIZE}
        total={total}
        onPrev={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
        onNext={() => setOffset(offset + PAGE_SIZE)}
      />
    </div>
  );
}

/**
 * Nothing on this tab. A search that matched nothing says so: "No requests
 * are waiting for approval" under a search box read as an empty queue while
 * a request waited under a name the search had missed.
 */
function QueueEmptyState({
  canDecide,
  search,
  statusFilter,
}: {
  canDecide: boolean;
  search: string;
  statusFilter: string;
}) {
  const { t } = useTranslation("approvals");
  if (search) {
    return (
      <div className="flex flex-col items-center justify-center py-16 text-center">
        <SearchX size={48} className="text-on-muted/40 mb-4" />
        <h3 className="text-lg font-medium text-on">
          {t("dashboard.noMatch", { search })}
        </h3>
        <p className="mt-1 max-w-md text-sm text-on-muted">
          {t("dashboard.noMatchHint")}
        </p>
      </div>
    );
  }
  return (
    <div className="flex flex-col items-center justify-center py-16 text-center">
      <DynamicIcon
        name={canDecide ? "CheckCheck" : "Lock"}
        size={48}
        className="text-on-muted/40 mb-4"
      />
      {/* The list is filtered by `approvals:approve` on the server, so
          without the grant it can only ever hold this reader's own
          requests — never the ones the generic hint describes. */}
      <h3 className="text-lg font-medium text-on">
        {emptyTitle(t, statusFilter, canDecide)}
      </h3>
      {statusFilter === OPEN_STATES && (
        <p className="mt-1 max-w-md text-sm text-on-muted">
          {canDecide
            ? t("dashboard.emptyHint")
            : t("dashboard.emptyNoDecideHint")}
        </p>
      )}
    </div>
  );
}

/**
 * Who an equipment checkout goes to and until when — what the approver is
 * deciding about. The request carries it (`meta_data.checkout`); one raised
 * without it covers the next checkout, whoever it goes to, and the card says
 * so rather than leaving the approver to guess.
 */
function CheckoutAskLine({ request }: { request: ApprovalRequest }) {
  const { t } = useTranslation("approvals");
  if (request.target_type !== "equipment_checkout") return null;
  const asked = (request.meta_data as { checkout?: CheckoutAsk } | null)
    ?.checkout;
  if (!asked?.holder) {
    return (
      <p className="text-sm text-on-muted">{t("dashboard.checkoutAnyone")}</p>
    );
  }
  return (
    <p className="flex flex-wrap items-center gap-1.5 text-sm text-on">
      <UserIcon size={14} className="text-on-muted" />
      <span>{t("dashboard.checkoutFor", { holder: asked.holder })}</span>
      {asked.expected_return_at && (
        <span className="text-on-secondary">
          {t("dashboard.checkoutUntil", {
            date: formatDate(asked.expected_return_at),
          })}
        </span>
      )}
    </p>
  );
}

type CheckoutAsk = { holder?: string; expected_return_at?: string | null };

function TargetTypeBadge({ targetType }: { targetType: string }) {
  const { t } = useTranslation("approvals");
  const labelKey = TARGET_TYPE_KEYS[targetType];
  const label = labelKey ? t(labelKey) : targetType;
  return (
    <span className="inline-flex items-center rounded-md bg-surface-inset px-2 py-0.5 text-xs font-medium text-on-secondary uppercase tracking-wide">
      {label}
    </span>
  );
}

function RequestCard({ request }: { request: ApprovalRequest }) {
  const { t } = useTranslation("approvals");
  const queryClient = useQueryClient();
  // A target type with a decide route of its own goes through it (see
  // `targetDecisionApi`); every other one falls back to the stage endpoint.
  const adapter = targetDecisionApi[request.target_type];
  const summary = request.target_summary;
  const currency = useDocumentCurrency(summary?.currency ?? null);
  const isDoc = request.target_type === "document";
  const targetHref = targetPath(request.target_type, request.target_id);
  const isCancelled = request.status === "CANCELLED";

  // Route through the target-type adapter when one exists; the
  // generic fallback lives inside ApprovalDecisionButtons. Both paths
  // refresh the queue so the card disappears once decided.
  const handleApprove = async (approval: ApprovalRequest, notes?: string) => {
    if (adapter) {
      await adapter.approve(approval.target_id, notes);
    }
    await queryClient.invalidateQueries({
      queryKey: queryKeys.approvals.requests,
    });
    // A settled request clears its own "waiting for your decision" notices on
    // the server; these adapters bypass the mutation hooks, so refresh the
    // bell here or it keeps counting them until the next poll.
    invalidation.notifications(queryClient);
  };

  const handleReject = async (approval: ApprovalRequest, notes: string) => {
    if (adapter) {
      await adapter.reject(approval.target_id, notes);
    }
    await queryClient.invalidateQueries({
      queryKey: queryKeys.approvals.requests,
    });
    // A settled request clears its own "waiting for your decision" notices on
    // the server; these adapters bypass the mutation hooks, so refresh the
    // bell here or it keeps counting them until the next poll.
    invalidation.notifications(queryClient);
  };

  const requester = request.created_by_name;
  const createdAt = formatDate(request.created_at);

  // Human-readable doc type label.
  const docTypeLabel = summary?.type
    ? t(`dashboard.docTypes.${summary.type}`, { defaultValue: summary.type })
    : null;

  // For documents without a partner
  // (typically INT — internal transfers), surface source→target
  // location as a meaningful fallback.
  const showLocationRoute =
    !!summary &&
    !summary.partner_name &&
    (summary.source_location_name || summary.target_location_name);

  return (
    <Card data-testid="approval-card">
      <CardContent className="p-5">
        <div className="space-y-4">
          {/* Header: badge + number + type + status | View document (outline) */}
          <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
            <div className="flex flex-wrap items-center gap-2">
              {/* both approval queues name the same record the same
                  way — the concrete document type leads; the generic target
                  badge remains only for non-document targets. */}
              {docTypeLabel ? (
                <span className="inline-flex items-center rounded-md bg-surface-inset px-2 py-0.5 text-xs font-medium text-on-secondary uppercase tracking-wide">
                  {docTypeLabel}
                </span>
              ) : (
                <TargetTypeBadge targetType={request.target_type} />
              )}
              <span className="text-lg font-semibold text-on tracking-tight">
                {summary?.number ??
                  (isDoc ? (
                    // For documents an absent summary means exactly one
                    // thing — the row is gone (deleting a document cascades a
                    // cancel onto its request). Say that instead of printing
                    // eight characters of a UUID nobody can act on.
                    <span className="text-on-muted">
                      {t("dashboard.targetDeleted")}
                    </span>
                  ) : (
                    <span className="font-mono text-on-muted">
                      {request.target_id.slice(0, 8)}…
                    </span>
                  ))}
              </span>
              <ApprovalBadge
                status={request.status}
                stage={{
                  current: request.current_stage,
                  total: request.total_stages,
                }}
              />
            </div>
            {/* No link to a target that is gone: the card has just said it was
                deleted, and the link would land on a 404. */}
            {targetHref && summary && (
              <Link
                to={targetHref}
                className={cn(
                  buttonVariants({ variant: "outline", size: "sm" }),
                  "gap-1.5 self-start sm:self-auto",
                )}
              >
                <ExternalLink size={14} />
                {t(TARGET_LINK_LABELS[request.target_type])}
              </Link>
            )}
          </div>

          {/* Requester prominent — the human behind the request
              is the most important signal for an approver's decision. */}
          {requester && (
            <p className="flex items-center gap-1.5 text-sm font-medium text-on">
              <UserIcon size={14} className="text-on-muted" />
              <span>{t("dashboard.requestedBy", { name: requester })}</span>
              <span className="text-xs font-normal text-on-muted">
                · {createdAt}
              </span>
            </p>
          )}

          <CheckoutAskLine request={request} />

          {/* Meta-row: partner / value / lines (or location route fallback) */}
          {summary && (
            <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm text-on-secondary">
              {summary.partner_name && (
                <span className="inline-flex items-center gap-1.5">
                  <UserIcon size={14} className="text-on-muted" />
                  {summary.partner_name}
                </span>
              )}
              {summary.serial_number && (
                <span className="inline-flex items-center gap-1.5">
                  <Barcode size={14} className="text-on-muted" />
                  {t("dashboard.targetSummary.serialNumber", {
                    serial: summary.serial_number,
                  })}
                </span>
              )}
              {summary.total_value != null && (
                <span className="inline-flex items-center gap-1.5 text-base font-semibold text-on">
                  <Coins size={14} className="text-on-muted" />
                  {t("dashboard.targetSummary.netAmount", {
                    amount: formatMoney(summary.total_value, currency ?? null),
                  })}
                </span>
              )}
              {summary.lines_count > 0 && (
                <span className="inline-flex items-center gap-1.5">
                  <ListOrdered size={14} className="text-on-muted" />
                  {t("dashboard.targetSummary.linesCount", {
                    count: summary.lines_count,
                  })}
                </span>
              )}
              {showLocationRoute && (
                <span className="inline-flex items-center gap-1.5 text-on-muted">
                  {t("dashboard.locationRoute", {
                    from: summary.source_location_name ?? "—",
                    to: summary.target_location_name ?? "—",
                  })}
                </span>
              )}
            </div>
          )}

          {/* stepper full width, decision at the foot of the card.
 on mobile the decision is the point of the screen —
              order it above the stepper so it is reachable without
              scrolling. */}
          <div className="flex flex-col gap-4">
            <div className="order-2 md:order-1">
              {/* A withdrawn request never reaches a stage, so
                  "Approval progress: Initial Review" under it read as though
                  it were still queued for that stage. */}
              {isCancelled ? (
                request.cancelled_at && (
                  <p className="text-xs text-on-muted">
                    {t("dashboard.cancelledOn", {
                      date: formatDate(request.cancelled_at),
                    })}
                  </p>
                )
              ) : (
                <>
                  <div className="mb-2 flex items-center justify-between gap-2">
                    <p className="text-[10px] font-medium uppercase tracking-widest text-on-muted">
                      {t("dashboard.section.approvalProgress")}
                    </p>
                    {request.total_stages > 1 && (
                      <span className="text-xs text-on-muted">
                        {t("dashboard.stepper.stageOfTotal", {
                          current: request.current_stage,
                          total: request.total_stages,
                        })}
                      </span>
                    )}
                  </div>
                  <ApprovalStageStepper
                    stages={request.workflow_stages}
                    currentStage={request.current_stage}
                    totalStages={request.total_stages}
                    status={request.status}
                    decisions={request.decisions}
                  />
                </>
              )}
            </div>
            <ApprovalDecisionPanel
              className="order-1 md:order-2"
              approval={request}
              onApprove={adapter ? handleApprove : undefined}
              onReject={adapter ? handleReject : undefined}
            />
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
