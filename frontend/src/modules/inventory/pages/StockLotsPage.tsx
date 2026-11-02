/**
 * StockLotsPage — /inventory/lots
 *
 * The batches, and which of them may not be touched.
 *
 * `StockLot.status` has carried quarantine, hold, expiry and recall since the
 * warehouse modules were written, and every picking path has obeyed it.
 * Nothing displayed it and nothing could change it: the person holding a
 * supplier's recall notice had no way to say so, and the person who had said
 * so had no way to take it back.
 *
 * Changing it asks why, and the answer is shown under the badge afterwards.
 * A status on its own says a decision was made; the row has to say which
 * decision, or the screen only records that somebody clicked.
 */
import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { Layers } from "lucide-react";
import { toast } from "sonner";
import { ListControlBar } from "@/components/ui/ListControlBar";
import { ActionMenu } from "@/components/ui/ActionMenu";
import { Badge } from "@/components/ui/Badge";
import { EmptyState } from "@/components/ui/EmptyState";
import { Pagination } from "@/module-sdk";
import LoadingSpinner from "@/components/LoadingSpinner";
import { QueryFailure } from "@/components/ui/QueryResult";
import { useModulePageHeader } from "@/hooks/useModulePageHeader";
import { useCanWrite } from "@/hooks/useCanWrite";
import { ReadOnlyNotice } from "@/components/ui/ReadOnlyNotice";
import { formatDate, formatDecimalQty } from "@/utils/formatters";
import { formatQuantityLocalized } from "@/lib/i18nHelpers";
import { useStockLots, useSetLotStatus } from "../hooks/useStockLots";
import {
  LotStatusDialog,
  type LotStatusRequest,
} from "../components/lots/LotStatusDialog";
import type { LotStatus } from "@/lib/api/stockLots";

const PAGE_SIZE = 50;

const STATUSES: LotStatus[] = [
  "active",
  "quarantined",
  "held",
  "expired",
  "recalled",
];

/** Held, quarantined and recalled all mean "do not pick it" — say which. */
const STATUS_TONE: Record<string, "success" | "warning" | "danger"> = {
  active: "success",
  quarantined: "warning",
  held: "warning",
  expired: "danger",
  recalled: "danger",
};

export default function StockLotsPage() {
  const { t } = useTranslation(["inventory", "common"]);
  const { setHeader } = useModulePageHeader();
  const [statusFilter, setStatusFilter] = useState<LotStatus | "all">("all");
  const [page, setPage] = useState(0);
  const [pending, setPending] = useState<LotStatusRequest | null>(null);
  const setStatus = useSetLotStatus();

  useEffect(() => {
    setHeader({
      title: t("inventory:lots.title"),
      subtitle: t("inventory:lots.subtitle"),
    });
  }, [setHeader, t]);

  useEffect(() => {
    setPage(0);
  }, [statusFilter]);

  const filters = useMemo(
    () => ({
      status: statusFilter === "all" ? undefined : statusFilter,
      limit: PAGE_SIZE,
      offset: page * PAGE_SIZE,
    }),
    [statusFilter, page],
  );

  // Holding a batch back is a stock write — `PATCH /stock-lots/{id}` asks for
  // `items:write`, the same key the products list is guarded by.
  const canWrite = useCanWrite("items");

  const { data, isLoading, isError, error, refetch } = useStockLots(filters);
  const lots = data?.items ?? [];
  const total = data?.total ?? 0;

  // Returns the promise: the dialog waits on it, and a refusal keeps the
  // dialog open with the reason still typed rather than losing both.
  const change = async (reason: string) => {
    if (!pending) return;
    const { lotId, status } = pending;
    await setStatus.mutateAsync({ lotId, status, reason });
    setPending(null);
    toast.success(
      t("inventory:lots.statusChanged", {
        status: t(`inventory:lot.status.${status}`),
      }),
    );
  };

  return (
    <div className="space-y-6">
      <ReadOnlyNotice module="items" />
      <ListControlBar
        primaryTabs={{
          value: statusFilter,
          onChange: (value) => setStatusFilter(value as LotStatus | "all"),
          options: [
            { value: "all", label: t("inventory:moves.direction.all") },
            ...STATUSES.map((value) => ({
              value,
              label: t(`inventory:lot.status.${value}`),
            })),
          ],
        }}
        resultCount={isError ? undefined : total}
        resultCountLabel={t("inventory:lots.count", { count: total })}
      />

      {isError ? (
        <QueryFailure error={error} onRetry={() => void refetch()} />
      ) : isLoading ? (
        <LoadingSpinner />
      ) : lots.length === 0 ? (
        <EmptyState
          icon={Layers}
          title={
            statusFilter === "all"
              ? t("inventory:lots.empty.title")
              : t("inventory:lots.empty.filteredTitle")
          }
          // The receiving hint answers "why is this empty" for an
          // organization without batches; under a status filter the answer
          // is the filter, not the goods-receiving process.
          description={
            statusFilter === "all"
              ? t("inventory:lots.empty.description")
              : t("inventory:lots.empty.filtered")
          }
        />
      ) : (
        <>
          <div className="bg-surface-card rounded-xl sm:rounded-2xl shadow-sm border border-border overflow-hidden">
            <div className="relative overflow-x-auto">
              <table className="w-full text-left border-collapse">
                <thead>
                  <tr className="bg-surface-raised border-b border-border text-xs font-medium text-on-secondary uppercase tracking-wider">
                    <th scope="col" className="px-4 py-3">
                      {t("inventory:lots.columns.batch")}
                    </th>
                    <th scope="col" className="px-4 py-3">
                      {t("inventory:lots.columns.product")}
                    </th>
                    <th scope="col" className="px-4 py-3">
                      {t("inventory:lots.columns.status")}
                    </th>
                    <th scope="col" className="px-4 py-3">
                      {t("inventory:lots.columns.expiry")}
                    </th>
                    <th scope="col" className="px-4 py-3 text-right">
                      {t("inventory:lots.columns.onHand")}
                    </th>
                    {canWrite && (
                      <th scope="col" className="px-4 py-3 w-12">
                        <span className="sr-only">
                          {t("inventory:lots.columns.actions")}
                        </span>
                      </th>
                    )}
                  </tr>
                </thead>
                <tbody>
                  {lots.map((lot) => (
                    <tr
                      key={lot.id}
                      className="border-b border-border last:border-0 text-sm hover:bg-surface-raised/50"
                    >
                      <td className="px-4 py-2.5">
                        <Link
                          to={`/inventory/lots/${lot.id}`}
                          className="text-primary-600 hover:text-primary-700 hover:underline"
                        >
                          {lot.name}
                        </Link>
                      </td>
                      <td className="px-4 py-2.5 text-on">
                        {lot.product_name ?? "—"}
                      </td>
                      <td className="px-4 py-2.5">
                        <Badge variant={STATUS_TONE[lot.status] ?? "secondary"}>
                          {t(`inventory:lot.status.${lot.status}`, {
                            defaultValue: lot.status,
                          })}
                        </Badge>
                        {/* Under the badge, not in a tooltip: "why is this
                            held" is the question the column is opened for,
                            and a hover is not an answer on a phone. */}
                        {lot.status_reason && (
                          <p className="mt-1 max-w-xs text-xs text-on-secondary break-words">
                            {lot.status_reason}
                          </p>
                        )}
                      </td>
                      <td className="px-4 py-2.5 text-on-secondary whitespace-nowrap">
                        {lot.expiry_date ? formatDate(lot.expiry_date) : "—"}
                      </td>
                      <td className="px-4 py-2.5 text-right tabular-nums text-on whitespace-nowrap">
                        {formatQuantityLocalized(
                          t,
                          formatDecimalQty(lot.on_hand),
                          lot.uom_symbol,
                        )}
                      </td>
                      {canWrite && (
                        <td className="px-4 py-2.5">
                          {/* The record's own actions live in the ⋯ menu, the
                            same as everywhere else in the app. */}
                          <ActionMenu
                            label={t("inventory:lots.actionsFor", {
                              name: lot.name,
                            })}
                            actions={STATUSES.filter(
                              (value) => value !== lot.status,
                            ).map((value) => ({
                              id: value,
                              label: t(`inventory:lots.setTo.${value}`),
                              onSelect: () =>
                                setPending({
                                  lotId: lot.id,
                                  lotName: lot.name,
                                  status: value,
                                }),
                            }))}
                          />
                        </td>
                      )}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
          <LotStatusDialog
            request={pending}
            onConfirm={change}
            onCancel={() => setPending(null)}
          />
          <Pagination
            skip={page * PAGE_SIZE}
            limit={PAGE_SIZE}
            total={total}
            onPrev={() => setPage((previous) => Math.max(0, previous - 1))}
            onNext={() => setPage((previous) => previous + 1)}
            onPageChange={(next) => setPage(next - 1)}
          />
        </>
      )}
    </div>
  );
}
