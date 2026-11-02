import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useNavigate } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import {
  Lock as LockIcon,
  Inbox,
  ExternalLink,
  User as UserIcon,
  Coins,
  ListOrdered,
  MapPin,
  ArrowRight,
  PackageCheck,
} from "lucide-react";
import { toast } from "sonner";

import { Card, CardContent } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { EmptyState } from "@/components/ui/EmptyState";
import { QueryError } from "@/components/ui/QueryResult";
import LoadingSpinner from "@/components/LoadingSpinner";
import { Pagination } from "@/module-sdk";
import { TypedSlot } from "@/components/Slot";
import { useHasPermission } from "@/hooks/useHasPermission";
import { DocumentStatusBadge } from "@/modules/warehouse/components/DocumentStatusBadge";
import { documentApprovalApi } from "@/modules/warehouse/api/documents";
import { useAwaitingApprovalDocuments } from "@/modules/warehouse/hooks/useAwaitingApprovalDocuments";
import { useDocumentLineNames } from "@/modules/warehouse/hooks/useDocumentLineNames";
import { useShowDocumentValue } from "@/modules/warehouse/hooks/useShowDocumentValue";
import {
  useApproveDocument,
  useDocumentApproval,
  useRejectDocument,
} from "@/modules/warehouse/hooks/useDocumentApproval";
import { useEnabledModulesOptional } from "@/contexts/ModulesContext";
import { useModulePageHeader } from "@/hooks/useModulePageHeader";
import { useDocumentCurrency } from "@/hooks/useDocumentCurrency";
import { invalidation } from "@/lib/api/invalidation";
import { queryKeys } from "@/hooks/queries/keys";
import { useMoney } from "@/hooks/useMoney";
import type { WarehouseDocument } from "@/modules/warehouse/types";
import { formatRecentMoment } from "@/utils/formatters";
import { formatQuantityLocalized } from "@/lib/i18nHelpers";

const PAGE_SIZE = 50;
const PREVIEW_LINES = 3;

export default function DocumentApprovalsPage() {
  const { t } = useTranslation("warehouse");
  const { setHeader } = useModulePageHeader();
  const enabledModules = useEnabledModulesOptional();
  const navigate = useNavigate();
  const canDecide = useHasPermission("approvals:approve");
  const [offset, setOffset] = useState(0);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [bulkApproving, setBulkApproving] = useState(false);
  const queryClient = useQueryClient();
  const { data, isLoading, isError, refetch } = useAwaitingApprovalDocuments({
    offset,
    limit: PAGE_SIZE,
  });
  const [confirmBulk, setConfirmBulk] = useState(false);

  // A request parked where nobody can decide it never reaches this queue —
  // the queue shows what the reader can act on, and there is nothing to act
  // on. So it reads exactly like an empty queue unless it is named here; the
  // approvals module names it.
  const parkedSection = (
    <TypedSlot
      name="approval_parked_requests"
      data={{
        targetType: "document",
        targetHref: (targetId) => `/warehouse/documents/${targetId}`,
      }}
    />
  );

  useEffect(() => {
    setHeader({
      title: t("approvalsQueue.title"),
      subtitle: t("approvalsQueue.subtitle"),
    });
  }, [t, setHeader]);

  const documents = data?.items ?? [];
  const total = data?.total ?? 0;

  const toggleSelected = (docId: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(docId)) {
        next.delete(docId);
      } else {
        next.add(docId);
      }
      return next;
    });
  };

  const handleBulkApprove = async () => {
    if (selected.size === 0 || bulkApproving) return;
    setConfirmBulk(false);
    setBulkApproving(true);
    const ids = [...selected];
    const results = await Promise.allSettled(
      ids.map((docId) => documentApprovalApi.approve(docId)),
    );
    setBulkApproving(false);

    // name the documents that did not go through. A bare count left
    // the approver to work out which of the twenty they still had to handle,
    // so the failures stay selected and the toast lists their numbers.
    const failedIds = ids.filter((_, i) => results[i].status === "rejected");
    const numberOf = (docId: string) =>
      documents.find((doc) => doc.id === docId)?.number ?? docId;
    if (failedIds.length > 0) {
      toast.error(
        t("approvalsQueue.bulkApproveFailed", {
          count: failedIds.length,
          numbers: failedIds.map(numberOf).join(", "),
        }),
      );
    } else {
      toast.success(
        t("approvalsQueue.bulkApproveSuccess", { count: ids.length }),
      );
    }
    setSelected(new Set(failedIds));
    void queryClient.invalidateQueries({
      queryKey: queryKeys.documents.awaitingApproval,
    });
    // Each approval marks the "waiting for your decision" notice read.
    invalidation.notifications(queryClient);
  };

  if (isLoading) {
    return <LoadingSpinner />;
  }

  if (isError) {
    // The empty state of this queue reads "nothing waiting on you" — the last
    // thing to show someone whose request simply failed.
    return (
      <QueryError
        message={t("errors.loadApprovalsFailed")}
        onRetry={() => void refetch()}
      />
    );
  }

  // The server fills this queue from `approvals:approve`. Without the grant
  // it answers 200 with nothing, for ever — so "documents you can approve
  // appear here" is not a description of today, it is a promise that cannot
  // be kept.
  if (documents.length === 0 && !canDecide) {
    return (
      <div className="space-y-3">
        {parkedSection}
        <EmptyState
          icon={LockIcon}
          title={t("approvalsQueue.emptyNoDecide")}
          description={t("approvalsQueue.emptyNoDecideHint")}
          secondaryAction={
            <Button
              variant="outline"
              size="sm"
              onClick={() => navigate("/warehouse")}
            >
              {t("approvalsQueue.emptyGoToDocuments")}
            </Button>
          }
        />
      </div>
    );
  }

  if (documents.length === 0) {
    return (
      <div className="space-y-3">
        {parkedSection}
        <EmptyState
          icon={Inbox}
          title={t("approvalsQueue.empty")}
          description={t("approvalsQueue.emptyHint")}
          primaryAction={
            // The hint used to name the Approvals module in prose, in a
            // workspace mode where that module does not exist — and called it
            // "cross-module", a word from this project's architecture rather
            // than from the reader's work.
            enabledModules.includes("approvals") ? (
              <Link
                to="/approvals"
                className="text-sm font-medium text-primary-600 hover:underline"
              >
                {t("approvalsQueue.emptyOtherModules")}
              </Link>
            ) : undefined
          }
          // When the approvals module is disabled the primary action above is
          // nothing, which left this screen a dead end. The documents list is
          // always reachable, so it is the permanent way out of the queue.
          secondaryAction={
            <Button
              variant="outline"
              size="sm"
              onClick={() => navigate("/warehouse")}
            >
              {t("approvalsQueue.emptyGoToDocuments")}
            </Button>
          }
        />
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {parkedSection}
      {selected.size > 0 && (
        <div className="sticky top-[calc(3.5rem+var(--app-notice-height,0px)+0.5rem)] md:top-[calc(3.5rem+2.75rem+var(--app-notice-height,0px)+0.5rem)] z-[var(--z-sticky)] flex items-center justify-between gap-3 rounded-lg border border-primary-200 bg-primary-50/95 px-3 py-2 backdrop-blur dark:border-primary-800 dark:bg-primary-950/80">
          <span className="text-sm font-medium text-primary-900 dark:text-primary-100">
            {t("approvalsQueue.selectedCount", { count: selected.size })}
          </span>
          <Button
            size="sm"
            variant="primary"
            leftIcon={<PackageCheck size={16} />}
            onClick={() => setConfirmBulk(true)}
            isLoading={bulkApproving}
          >
            {t("approvalsQueue.bulkApprove", { count: selected.size })}
          </Button>
        </div>
      )}

      {documents.map((doc) => (
        <ApprovalRequestCard
          key={doc.id}
          doc={doc}
          selected={selected.has(doc.id)}
          onToggleSelected={() => toggleSelected(doc.id)}
        />
      ))}

      <Pagination
        skip={offset}
        limit={PAGE_SIZE}
        total={total}
        onPrev={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
        onNext={() => setOffset(offset + PAGE_SIZE)}
      />

      {/* Approving in bulk confirms every one of these documents for
          warehouse execution (the stock moves later, at the receipt) and
          cannot be undone from here — the one action on this screen that
          earns a confirmation. */}
      <ConfirmDialog
        open={confirmBulk}
        title={t("approvalsQueue.bulkApproveConfirmTitle")}
        message={t("approvalsQueue.bulkApproveConfirmMessage", {
          count: selected.size,
        })}
        confirmLabel={t("approvalsQueue.bulkApprove", { count: selected.size })}
        onConfirm={() => void handleBulkApprove()}
        onCancel={() => setConfirmBulk(false)}
      />
    </div>
  );
}

interface ApprovalRequestCardProps {
  doc: WarehouseDocument;
  selected: boolean;
  onToggleSelected: () => void;
}

function ApprovalRequestCard({
  doc: storedDoc,
  selected,
  onToggleSelected,
}: ApprovalRequestCardProps) {
  const { t } = useTranslation("warehouse");
  // A line stored before the name was written onto it carries only the
  // item it moves: the preview read a bare "× 5 pcs." for a record the
  // approver could not identify. The name comes from the item itself — the
  // same read-time fallback the document detail reads its lines through.
  const doc = useDocumentLineNames(storedDoc) ?? storedDoc;
  const { t: tApprovals } = useTranslation("approvals");
  const { data: approval } = useDocumentApproval(doc.id);
  const approveDocument = useApproveDocument();
  const rejectDocument = useRejectDocument();
  const currency = useDocumentCurrency(doc.currency ?? null);
  const money = useMoney();
  // The amount a card quotes follows the same two rules the row in the
  // document list follows: the organization tracks value, and this
  // document is one whose lines carry a price.
  const showValue = useShowDocumentValue(doc.type);

  // Human-readable doc type — mirrors the approvals dashboard
  // so the queue reads the same as the cross-module inbox.
  const docTypeLabel = tApprovals(`dashboard.docTypes.${doc.type}`, {
    defaultValue: doc.type,
  });

  const previewLines = useMemo(
    () => doc.lines.slice(0, PREVIEW_LINES),
    [doc.lines],
  );
  const hiddenLines = doc.lines.length - previewLines.length;

  const route = [doc.source_location_name, doc.target_location_name]
    .filter(Boolean)
    .join("");

  return (
    <Card>
      <CardContent className="p-5">
        {/* Two columns from xl (UI_GUIDELINES §3.2b): the document facts sit
            beside the approval progress instead of stacking into a tall
            half-empty card. Below xl the decision block still comes first
            (order-1), the facts after it. */}
        <div className="grid grid-cols-1 gap-x-8 gap-y-4 xl:grid-cols-12">
          {/* the number is the link to the document. "Open document"
              beside it pointed at the same place — two links, one target,
              one row. The header row spans both columns. */}
          <div className="xl:col-span-12">
            <div className="flex flex-wrap items-center gap-2">
              <input
                type="checkbox"
                checked={selected}
                onChange={onToggleSelected}
                /* twenty rows all announced as "Select" told a
                   screen-reader user nothing about which document they were
                   about to approve in bulk. */
                aria-label={t("approvalsQueue.selectDocument", {
                  number: doc.number,
                })}
                className="h-4 w-4 shrink-0 accent-primary-600"
              />
              <span className="inline-flex items-center rounded-md bg-surface-inset px-2 py-0.5 text-xs font-medium text-on-secondary uppercase tracking-wide">
                {docTypeLabel}
              </span>
              {/* The number is the one link to the document, so it
                  has to look like one: without the icon the only way to the
                  document was a hover state a touch screen never shows. */}
              <Link
                to={`/warehouse/documents/${doc.id}`}
                className="inline-flex items-center gap-1.5 text-lg font-semibold text-on tracking-tight underline-offset-4 hover:underline"
              >
                {doc.number}
                <ExternalLink size={14} className="text-on-muted" />
              </Link>
              {/* the queue shows the approval-request state machine;
                  the document state machine stays on the detail page. This
                  matches the /approvals inbox badge for the same record. */}
              {approval ? (
                <TypedSlot
                  name="approval_request_badge"
                  data={{ status: approval.status }}
                  fallback={<DocumentStatusBadge status={doc.status} />}
                />
              ) : (
                <DocumentStatusBadge status={doc.status} />
              )}
            </div>
          </div>

          {/* The facts of what is being decided. */}
          <section className="flex flex-col gap-3 order-2 xl:order-1 xl:col-span-7">
            {/* Requester prominent (mirrors ApprovalsDashboard); how long
                the request has waited is part of the decision. Both are the
                request's: the document's author and creation date are
                another record, and nothing stands in for the request while
                it loads. */}
            {approval?.created_by_name && (
              <p className="flex flex-wrap items-center gap-1.5 text-sm font-medium text-on">
                <UserIcon size={14} className="text-on-muted" />
                <span>{approval.created_by_name}</span>
                <span className="text-xs font-normal text-on-muted">
                  {t("approvalsQueue.requester")}
                </span>
                <span className="text-xs font-normal text-on-muted">
                  · {formatRecentMoment(approval.created_at)}
                </span>
              </p>
            )}

            {/* Meta-row: partner, route, value, lines */}
            <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm text-on-secondary">
              {doc.partner_snapshot?.name && (
                <span className="inline-flex items-center gap-1.5">
                  <UserIcon size={14} className="text-on-muted" />
                  {doc.partner_snapshot.name}
                </span>
              )}
              {route && (
                <span className="inline-flex items-center gap-1.5">
                  <MapPin size={14} className="text-on-muted" />
                  {/* each end wrapped in its own element, so the two names
                      read the way the ledger renders its places */}
                  <span>{doc.source_location_name}</span>
                  {doc.source_location_name && doc.target_location_name && (
                    <ArrowRight size={12} className="text-on-muted" />
                  )}
                  <span>{doc.target_location_name}</span>
                </span>
              )}
              {showValue && doc.total_gross != null && (
                <span className="inline-flex items-center gap-1.5 text-base font-semibold text-on">
                  <Coins size={14} className="text-on-muted" />
                  {money(doc.total_gross, currency ?? null)}
                </span>
              )}
              <span className="inline-flex items-center gap-1.5">
                <ListOrdered size={14} className="text-on-muted" />
                {t("targetSummary.linesCount", {
                  count: doc.lines.length,
                })}
              </span>
            </div>

            {/* first lines with quantities so the approver sees
                what they are signing off without opening the document. The
                unit travels with the number — the same one-string rule the
                ledger's quantity column follows. */}
            {previewLines.length > 0 && (
              <ul className="flex flex-wrap gap-x-5 gap-y-1 text-sm text-on-secondary">
                {previewLines.map((line) => (
                  <li key={line.id} className="flex items-center gap-1.5">
                    <span className="text-on">{line.name}</span>
                    <span className="text-on-muted tabular-nums">
                      {" "}
                      ×{" "}
                      {formatQuantityLocalized(
                        t,
                        line.quantity,
                        line.uom?.symbol,
                      )}
                    </span>
                  </li>
                ))}
                {hiddenLines > 0 && (
                  <li className="text-on-muted">
                    {t("approvalsQueue.moreLines", { count: hiddenLines })}
                  </li>
                )}
              </ul>
            )}
          </section>

          {/* The progress and the decision, in the narrower column with its
              own rule: the shared panel keeps the caption and the action row
              together at the column's edge. */}
          {approval && (
            <section className="flex flex-col gap-4 order-1 xl:order-2 xl:col-span-5 xl:border-l xl:border-border xl:pl-8">
              {/* Inline approve/reject via the shared decision panel. The
                  adapters route through the document-specific endpoints so
                  the approve triggers the atomic confirm transition and
                  the reject triggers the rework loop (doc -> DRAFT +
                  requester notification), and their invalidation refreshes the
                  queue plus this card's approval query. Without these
                  adapters the generic /approvals/requests/{id}/reject would
                  leave the document stuck in PENDING_APPROVAL — exactly the
                  dead-end the document-specific endpoints avoid. */}
              <TypedSlot
                name="approval_decision_panel"
                data={{
                  approval,
                  onApprove: async (req, notes) => {
                    await approveDocument.mutateAsync({
                      docId: req.target_id,
                      notes,
                    });
                  },
                  onReject: async (req, notes) => {
                    await rejectDocument.mutateAsync({
                      docId: req.target_id,
                      notes,
                    });
                  },
                }}
              />
            </section>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
