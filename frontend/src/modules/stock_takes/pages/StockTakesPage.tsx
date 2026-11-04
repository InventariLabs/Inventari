import { useState, useEffect } from "react";
import { makeTDynamic } from "@/lib/i18nHelpers";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import {
  Plus,
  Package,
  AlertCircle,
  CheckCircle,
  Clock,
  XCircle,
  ChevronRight,
  ClipboardCheck,
  Trash2,
  Settings,
} from "lucide-react";
import LoadingSpinner from "@/components/LoadingSpinner";
import {
  useStockTakes,
  useDeleteStockTake,
} from "@/modules/stock_takes/hooks/useStockTakes";
import type {
  StockTakeSummary,
  StockTakeStatus,
} from "@/modules/stock_takes/types/stock-takes";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { Pagination } from "@/module-sdk";
import { cn } from "@/lib/utils";
import { formatDateTime, formatPercentLocale } from "@/utils/formatters";
import { useConfirm } from "@/hooks/useConfirm";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import StockTakeCreateModal from "../components/StockTakeCreateModal";
import { useModulePageHeader } from "@/hooks/useModulePageHeader";
import { useReturnTarget } from "@/hooks/useReturnTarget";
import { useCanWrite } from "@/hooks/useCanWrite";
import { useHasPermission } from "@/hooks/useHasPermission";
import { ReadOnlyNotice } from "@/components/ui/ReadOnlyNotice";
import { ListControlBar } from "@/components/ui/ListControlBar";
import { QueryError } from "@/components/ui/QueryResult";

const PAGE_SIZE = 50;

// older API responses may omit progress_percent — the counts are
// already in the payload, so compute the percentage locally instead of
// silently showing 0 %.
function progressPercentOf(stockTake: StockTakeSummary): number {
  if (stockTake.progress_percent != null) return stockTake.progress_percent;
  if (stockTake.items_count > 0) {
    return (stockTake.counted_items_count / stockTake.items_count) * 100;
  }
  return 0;
}

/**
 * Where a row leads: the count screen while there is counting left to do,
 * the report once there is not. One function so the card's title and its
 * status button can never point at different places.
 */
function destinationOf(stockTake: StockTakeSummary): string {
  const base = `/inventory/stock-takes/${stockTake.id}`;
  return stockTake.status === "completed"
    ? `${base}/report`
    : `${base}/counting`;
}

/**
 * How often every location falls due for a count is this module's setting,
 * and the module has no bar of its own to hold the entry: an admin gets
 * there from the list.
 */
function ModuleSettingsLink() {
  const { t } = useTranslation("common");
  const isAdmin = useHasPermission("admin:access");
  if (!isAdmin) return null;
  return (
    <div className="flex justify-end">
      <Link
        to="/settings/modules/stock_takes"
        className="inline-flex min-h-6 items-center gap-1 text-sm text-on-secondary underline hover:text-on md:min-h-0"
      >
        <Settings size={14} />
        {t("common:settings.moduleSettings.open")}
      </Link>
    </div>
  );
}

/** The launcher's "in progress" row counts those, and opens them here. */
function urlStatus(params: URLSearchParams): StockTakeStatus | "" {
  return params.get("status") === "in_progress" ? "in_progress" : "";
}

export default function StockTakesPage() {
  const { t } = useTranslation(["stock_takes", "common"]);
  const tDyn = makeTDynamic(t);
  // A location's own screens link here with `?new=<location>`: the form opens
  // with that place chosen, so a count can start where the reader stands.
  const [searchParams, setSearchParams] = useSearchParams();
  const presetStorageId = searchParams.get("new") ?? undefined;
  const [isModalOpen, setIsModalOpen] = useState(Boolean(presetStorageId));
  const [statusFilter, setStatusFilter] = useState(urlStatus(searchParams));
  const [offset, setOffset] = useState(0);
  const { confirm, confirmDialogProps } = useConfirm();
  const { setHeader } = useModulePageHeader();
  const backTo = useReturnTarget();
  const canWrite = useCanWrite("stock_takes");
  const navigate = useNavigate();

  const {
    data: stockTakesData,
    isLoading,
    isError,
    refetch,
  } = useStockTakes(statusFilter as StockTakeStatus | "", {
    offset,
    limit: PAGE_SIZE,
  });
  const total = stockTakesData?.total ?? 0;

  const deleteMutation = useDeleteStockTake();

  useEffect(() => {
    setHeader({
      title: t("title"),
      backTo,
      actions: canWrite ? (
        <div className="ml-auto flex flex-wrap gap-2">
          <Button
            variant="outline"
            onClick={() => navigate("/inventory/stock-takes/count")}
            leftIcon={<ClipboardCheck size={16} />}
          >
            {t("count.action")}
          </Button>
          <Button
            onClick={() => setIsModalOpen(true)}
            leftIcon={<Plus size={16} />}
          >
            {t("newStockTake")}
          </Button>
        </div>
      ) : undefined,
    });
  }, [t, setHeader, canWrite, backTo, navigate]);

  if (isLoading) {
    return <LoadingSpinner />;
  }
  // "No stock takes" over nine counts in progress invites a tenth count of a
  // location somebody is already walking.
  if (isError) {
    return <QueryError onRetry={refetch} />;
  }

  return (
    <div className="space-y-6 animate-in fade-in slide-in-from-bottom-4 duration-300">
      <ReadOnlyNotice module="stock_takes" />
      <ModuleSettingsLink />
      <ListControlBar
        primaryTabs={{
          value: statusFilter,
          onChange: (v) => {
            setStatusFilter(v as StockTakeStatus | "");
            setOffset(0);
          },
          options: [
            { value: "", label: t("all") },
            {
              value: "in_progress",
              label: tDyn("statusFilters.in_progress"),
              icon: <Clock size={14} />,
            },
            {
              value: "completed",
              label: tDyn("statusFilters.completed"),
              icon: <CheckCircle size={14} />,
            },
            {
              value: "cancelled",
              label: tDyn("statusFilters.cancelled"),
              icon: <XCircle size={14} />,
            },
          ],
        }}
      />

      {/* Stock Takes List */}
      {stockTakesData && stockTakesData.items.length > 0 ? (
        <div className="grid grid-cols-1 gap-6">
          {stockTakesData.items.map((stockTake) => (
            <Card
              key={stockTake.id}
              hoverable
              className="group relative flex flex-col sm:flex-row sm:items-center justify-between p-4 sm:p-5 gap-6 focus-within:border-primary-300"
            >
              <div className="flex-1 flex flex-col sm:flex-row sm:items-center gap-6">
                <div className="flex flex-col gap-1">
                  <div className="flex items-center gap-3 mb-1">
                    <Badge
                      variant={
                        stockTake.status === "completed"
                          ? "success"
                          : stockTake.status === "in_progress"
                            ? "info"
                            : "secondary"
                      }
                      className="text-[10px] px-2 py-0.5"
                    >
                      {tDyn(`statuses.${stockTake.status}`)}
                    </Badge>
                    {stockTake.discrepancies_count > 0 && (
                      <Badge
                        variant="danger"
                        className="text-[10px] px-2 py-0.5 flex items-center gap-1"
                      >
                        <AlertCircle size={10} />
                        {t("differencesBadge", {
                          count: stockTake.discrepancies_count,
                        })}
                      </Badge>
                    )}
                  </div>
                  <h3 className="text-lg font-semibold text-on group-hover:text-primary-600 transition-colors leading-tight">
                    {/* The card promised a click with a hover lift and a
                        colour change on this title, and delivered one only
                        from the button at the far end. The title is the link
                        now, stretched over the card (§2.3a). */}
                    <Link
                      to={destinationOf(stockTake)}
                      className="after:absolute after:inset-0 after:content-[''] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary-500/40 rounded-sm"
                    >
                      {stockTake.name}
                    </Link>
                  </h3>
                  <p className="text-xs font-medium text-on-secondary uppercase tracking-wide flex items-center gap-1.5 mt-1">
                    <Package size={12} className="text-on-muted" />
                    {stockTake.location_name || t("unknownPlace")}
                  </p>
                </div>

                <div className="sm:border-l sm:border-border sm:pl-6 flex flex-col gap-1.5">
                  <p className="text-[10px] font-medium text-on-muted uppercase tracking-wide">
                    {t("started")}
                  </p>
                  <p className="text-sm font-medium text-on-secondary">
                    {formatDateTime(stockTake.started_at)}
                  </p>
                  {/* The list is how somebody returns to their own count, and
                      the card used to say when but never by whom. */}
                  {stockTake.started_by_name && (
                    <p className="text-xs text-on-muted">
                      {stockTake.started_by_name}
                    </p>
                  )}
                </div>

                <div className="flex-1 max-w-[200px] flex flex-col gap-2">
                  <div className="flex justify-between items-end">
                    <p className="text-[10px] font-medium text-on-muted uppercase tracking-wide">
                      {t("progressLabel")}
                    </p>
                    <p className="text-xs font-medium text-primary-700">
                      {formatPercentLocale(progressPercentOf(stockTake), 0)}
                    </p>
                  </div>
                  <div className="w-full h-2 bg-surface-raised rounded-full overflow-hidden">
                    <div
                      className={cn(
                        "h-full transition-all duration-1000",
                        stockTake.status === "completed"
                          ? "bg-accent-500"
                          : "bg-primary-500",
                      )}
                      style={{ width: `${progressPercentOf(stockTake)}%` }}
                    />
                  </div>
                  <p className="text-[10px] font-medium text-on-muted text-right">
                    {stockTake.counted_items_count} / {stockTake.items_count}
                  </p>
                </div>
              </div>

              {/* Above the stretched link, or none of it could be pressed.
                  The three status links lead where the title leads, so they
                  are hidden from assistive technology as duplicates — the
                  status badge above already says which state the row is in. */}
              <div className="relative z-10 flex items-center gap-3 shrink-0">
                {/* Counting is the write; the report is not. A reader keeps
                    the way in to a finished count and loses the two that
                    open the counting screen. */}
                {stockTake.status === "in_progress" && canWrite && (
                  <Link
                    to={destinationOf(stockTake)}
                    tabIndex={-1}
                    aria-hidden="true"
                  >
                    <Button
                      variant="primary"
                      size="contentSm"
                      className="h-10 px-5"
                      tabIndex={-1}
                    >
                      {t("continue")}
                    </Button>
                  </Link>
                )}
                {stockTake.status === "draft" && canWrite && (
                  <Link
                    to={destinationOf(stockTake)}
                    tabIndex={-1}
                    aria-hidden="true"
                  >
                    <Button
                      variant="primary"
                      size="contentSm"
                      className="h-10 px-5"
                      tabIndex={-1}
                    >
                      {t("start")}
                    </Button>
                  </Link>
                )}
                {stockTake.status === "completed" && (
                  <Link
                    to={destinationOf(stockTake)}
                    tabIndex={-1}
                    aria-hidden="true"
                  >
                    <Button
                      variant="outline"
                      size="contentSm"
                      className="h-10 px-5"
                      rightIcon={<ChevronRight size={14} />}
                      tabIndex={-1}
                    >
                      {t("report.title")}
                    </Button>
                  </Link>
                )}
                {canWrite &&
                  (stockTake.status === "draft" ||
                    stockTake.status === "in_progress") && (
                    <Button
                      variant="ghostDanger"
                      size="icon"
                      onClick={async () => {
                        if (
                          await confirm({
                            title: t("common:actions.delete"),
                            message: t("confirmDelete"),
                            variant: "danger",
                            confirmLabel: t("common:actions.delete"),
                          })
                        ) {
                          deleteMutation.mutate(stockTake.id);
                        }
                      }}
                      className="text-on-muted hover:text-red-600 dark:hover:text-red-400 hover:bg-red-50 dark:hover:bg-red-500/10"
                      aria-label={t("deleteAriaLabel")}
                    >
                      <Trash2 size={18} />
                    </Button>
                  )}
              </div>
            </Card>
          ))}
        </div>
      ) : (
        <div className="flex flex-col items-center justify-center py-16 text-center">
          <ClipboardCheck size={48} className="text-on-muted/40 mb-4" />
          <h3 className="text-lg font-semibold text-on mb-1">
            {t("empty.title")}
          </h3>
          <p className="text-sm text-on-muted mb-6 max-w-md">
            {statusFilter
              ? t("empty.noStatus", {
                  status: tDyn(`statuses.${statusFilter}`),
                })
              : t("empty.addFirst")}
          </p>
          {canWrite && (
            <Button
              onClick={() => setIsModalOpen(true)}
              leftIcon={<Plus size={16} />}
            >
              {t("newStockTake")}
            </Button>
          )}
        </div>
      )}

      <StockTakeCreateModal
        isOpen={isModalOpen}
        initialStorageId={presetStorageId}
        onClose={() => {
          setIsModalOpen(false);
          if (presetStorageId) setSearchParams({}, { replace: true });
        }}
      />

      <Pagination
        skip={offset}
        limit={PAGE_SIZE}
        total={total}
        onPrev={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
        onNext={() => setOffset(offset + PAGE_SIZE)}
      />

      <ConfirmDialog {...confirmDialogProps} />
    </div>
  );
}
