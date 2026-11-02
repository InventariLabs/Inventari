import { useTranslation } from "react-i18next";
import { CheckCircle2, Plus, Trash2, Wrench } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import LoadingSpinner from "@/components/LoadingSpinner";
import { formatMoney } from "@/utils/formatters";
import { formatDate } from "@/utils/helpers";
import {
  useItemMaintenanceLogs,
  useDeleteMaintenanceLog,
} from "@/modules/equipment/hooks/useEquipment";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { useConfirm } from "@/hooks/useConfirm";
import { useOrganizationCurrency } from "@/hooks/useOrganizationCurrency";
import { getEquipmentMeta } from "@/modules/equipment/components/assetUtils";
import type { Item } from "@/types";
import type { MaintenanceLog } from "@/modules/equipment/api/equipment";
import { EmptyState } from "@/components/ui/EmptyState";
import { QueryFailure } from "@/components/ui/QueryResult";

const MAINTENANCE_TYPE_ICONS: Record<string, React.ReactNode> = {
  REPAIR: <Wrench size={14} className="text-red-500" />,
  CLEANING: <Wrench size={14} className="text-primary-500" />,
  UPGRADE: <Wrench size={14} className="text-purple-500" />,
  INSPECTION: <Wrench size={14} className="text-amber-500" />,
  OTHER: <Wrench size={14} className="text-on-muted" />,
};

interface MaintenanceTabProps {
  item: Item;
  onAdd: () => void;
  /**
   * End the asset's service: the card's way out of the state this tab
   * displays. The return that opens the workshop door lands the reader here,
   * so the door out belongs here too — once as a status buried in a header
   * menu is once too few.
   */
  onEndService?: () => void;
  /** A status change is in flight; the button must not send a second one. */
  endServicePending?: boolean;
  /** Logging and removing entries are writes; a reader gets neither. */
  canWrite?: boolean;
}

export function MaintenanceTab({
  item,
  onAdd,
  onEndService,
  endServicePending = false,
  canWrite = true,
}: MaintenanceTabProps) {
  const { t, i18n } = useTranslation(["equipment", "common"]);
  const lang = i18n.language?.substring(0, 2) ?? "en";
  const orgCurrency = useOrganizationCurrency();
  const {
    data: logs = [],
    isLoading,
    isError,
    error,
    refetch,
  } = useItemMaintenanceLogs(item.id);
  const deleteMutation = useDeleteMaintenanceLog();

  // The trash icon must confirm before deleting an irreversible row.
  const { confirm, confirmDialogProps } = useConfirm();

  async function handleDelete(log: MaintenanceLog): Promise<void> {
    const ok = await confirm({
      title: t("maintenance.confirmDeleteTitle"),
      message: t("maintenance.confirmDeleteMessage", {
        title: log.title,
      }),
      variant: "danger",
      confirmLabel: t("common:actions.delete"),
    });
    if (ok) {
      deleteMutation.mutate(log.id);
    }
  }

  // the running total is the reason costs get logged at all — it is
  // what tells you whether an asset is worth keeping. Entries without a cost
  // are skipped rather than counted as zero.
  const totalCost = logs.reduce(
    (sum: number, log: MaintenanceLog) =>
      log.cost != null && Number.isFinite(Number(log.cost))
        ? sum + Number(log.cost)
        : sum,
    0,
  );
  const hasCosts = logs.some(
    (log: MaintenanceLog) =>
      log.cost != null && Number.isFinite(Number(log.cost)),
  );

  // The state this tab explains must also offer its exit. The header's
  // "Change status" menu can set Available, but it names none of this — a
  // reader who opened the tab to ask why the asset is in service finds the
  // answer and the way out in the same place.
  const inService = getEquipmentMeta(item).status === "MAINTENANCE";
  // An archived record keeps its history and its entries stay removable,
  // but a new entry and a status change need the live record — the API
  // refuses both, so neither is offered.
  const archived = Boolean(item.is_deleted);

  return (
    <div className="space-y-4">
      {inService && canWrite && !archived && onEndService && (
        <div
          className="flex flex-wrap items-center justify-between gap-3 rounded-xl bg-amber-50 px-4 py-3"
          data-testid="maintenance-in-service"
        >
          <div className="flex min-w-0 items-start gap-3">
            <Wrench size={18} className="mt-0.5 shrink-0 text-on-warning" />
            <div className="min-w-0">
              <p className="text-sm font-semibold text-on-warning">
                {t("maintenance.in_service_title")}
              </p>
              <p className="mt-0.5 text-xs text-on-secondary">
                {t("maintenance.in_service_hint")}
              </p>
            </div>
          </div>
          <Button
            size="sm"
            variant="outline"
            leftIcon={<CheckCircle2 size={16} />}
            onClick={onEndService}
            disabled={endServicePending}
          >
            {t("maintenance.end_service")}
          </Button>
        </div>
      )}

      <div className="flex items-center justify-between gap-3">
        {hasCosts ? (
          <span
            className="text-sm text-on-secondary"
            data-testid="maintenance-total-cost"
          >
            {t("maintenance.total_cost")}:{" "}
            <span className="font-medium text-on">
              {formatMoney(totalCost, orgCurrency, lang)}
            </span>
          </span>
        ) : (
          <span />
        )}
        {canWrite && !archived && (
          <Button
            size="sm"
            variant="outline"
            leftIcon={<Plus size={16} />}
            onClick={onAdd}
          >
            {t("maintenance.add_log")}
          </Button>
        )}
      </div>

      {isError ? (
        <QueryFailure error={error} onRetry={() => refetch()} />
      ) : isLoading ? (
        <LoadingSpinner />
      ) : logs.length === 0 ? (
        <EmptyState variant="compact" title={t("maintenance.no_history")} />
      ) : (
        <div className="space-y-2">
          {logs.map((log: MaintenanceLog) => (
            <Card key={log.id} className="p-4">
              <div className="flex items-start gap-3">
                <div className="flex-shrink-0 mt-0.5">
                  {MAINTENANCE_TYPE_ICONS[log.maintenance_type] ?? (
                    <Wrench size={14} />
                  )}
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="font-medium text-sm text-on">
                      {log.title}
                    </span>
                    <Badge variant="secondary" className="text-xs">
                      {t(
                        `maintenance.type_${log.maintenance_type.toLowerCase()}`,
                      )}
                    </Badge>
                  </div>
                  {log.description && (
                    <p className="mt-1 text-xs text-on-muted line-clamp-2">
                      {log.description}
                    </p>
                  )}
                  <div className="mt-1 flex items-center gap-3 text-xs text-on-muted">
                    <span>
                      {t("maintenance.performed_at")}:{" "}
                      {formatDate(log.performed_at)}
                    </span>
                    {log.performed_by && (
                      <span>
                        {t("maintenance.performed_by")}: {log.performed_by}
                      </span>
                    )}
                    {log.cost != null && (
                      <span>
                        {t("maintenance.cost")}:{" "}
                        {formatMoney(
                          log.cost,
                          log.currency ?? orgCurrency,
                          lang,
                        )}
                      </span>
                    )}
                  </div>
                  {log.next_maintenance_at && (
                    <div className="mt-1 text-xs text-amber-600 dark:text-amber-400">
                      {t("maintenance.next_maintenance")}:{" "}
                      {formatDate(log.next_maintenance_at)}
                    </div>
                  )}
                </div>
                {canWrite && (
                  <Button
                    type="button"
                    variant="ghost"
                    size="iconSm"
                    onClick={() => void handleDelete(log)}
                    className="text-on-muted hover:text-red-500 transition-colors"
                    aria-label={t("maintenance.deleteAriaLabel")}
                    disabled={deleteMutation.isPending}
                  >
                    <Trash2 size={14} />
                  </Button>
                )}
              </div>
            </Card>
          ))}
        </div>
      )}

      <ConfirmDialog {...confirmDialogProps} />
    </div>
  );
}
