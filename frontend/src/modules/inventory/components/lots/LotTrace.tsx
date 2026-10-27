/**
 * LotTrace — the recall question, answered per source rather than per row.
 *
 * One step back and one step forward: the receipts that brought the batch in
 * and the deliveries and runs that sent it out, each with its partner, date
 * and quantity. A run that made another batch of it leads there, and that
 * batch's own customers follow below, because a recall of an ingredient is a
 * recall of what was made from it.
 *
 * The movement ledger under this section still lists every row; this is the
 * page an inspector is handed, which is why it exports.
 */
import { useCallback } from "react";
import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { FileDown } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import LoadingSpinner from "@/components/LoadingSpinner";
import { QueryError } from "@/components/ui/QueryResult";
import { extractApiError } from "@/lib/errors";
import {
  formatDate,
  formatDecimalQty,
  getTodayFilename,
} from "@/utils/formatters";
import { downloadBlob } from "@/utils/helpers";
import { formatQuantityLocalized } from "@/lib/i18nHelpers";
import {
  stockLotsApi,
  type LotTraceEntry,
  type LotTraceLot,
} from "@/lib/api/stockLots";
import { useLotTrace } from "../../hooks/useStockLot";
import { useMoveSourceLink } from "../../moveSourceLink";

function Source({ entry }: { entry: LotTraceEntry }) {
  const { t } = useTranslation("inventory");
  const sourceLink = useMoveSourceLink();
  const href = sourceLink(entry);
  const kind = entry.reference_type
    ? t(`inventory:moves.source.${entry.reference_type}`, {
        defaultValue: entry.reference_type,
      })
    : t("inventory:lot.trace.unknownSource");
  const label = entry.label ?? kind;
  return (
    <span className="min-w-0">
      {entry.label && (
        <span className="block text-xs text-on-muted">{kind}</span>
      )}
      {href ? (
        <Link to={href} className="text-sm text-primary-600 hover:underline">
          {label}
        </Link>
      ) : (
        <span className="text-sm text-on">{label}</span>
      )}
    </span>
  );
}

function Made({ entry }: { entry: LotTraceEntry }) {
  const { t } = useTranslation("inventory");
  if (!entry.produced?.length) return null;
  return (
    <ul className="mt-1 space-y-0.5">
      {entry.produced.map((made) => (
        <li key={made.lot_id} className="text-xs text-on-secondary">
          {t("inventory:lot.trace.madeInto")}{" "}
          <Link
            to={`/inventory/lots/${made.lot_id}`}
            className="text-primary-600 hover:underline"
          >
            {made.lot_name}
          </Link>
          {made.product_name ? ` · ${made.product_name}` : ""} ·{" "}
          <span className="tabular-nums">
            {formatQuantityLocalized(
              t,
              formatDecimalQty(made.quantity),
              made.uom_symbol,
            )}
          </span>
        </li>
      ))}
    </ul>
  );
}

function EntryRow({
  entry,
  uom,
}: {
  entry: LotTraceEntry;
  uom: string | null | undefined;
}) {
  const { t } = useTranslation("inventory");
  return (
    <li className="px-4 py-3 grid grid-cols-1 sm:grid-cols-[7rem_minmax(0,1fr)_minmax(0,1.5fr)_8rem] gap-x-4 gap-y-1 items-start">
      <span className="text-sm tabular-nums text-on-secondary whitespace-nowrap">
        {formatDate(entry.moved_at)}
      </span>
      <Source entry={entry} />
      <span className="min-w-0 text-sm break-words">
        {entry.partner_name ? (
          <>
            <span className="text-on">{entry.partner_name}</span>
            {entry.partner_address && (
              <span className="block text-xs text-on-secondary">
                {entry.partner_address}
              </span>
            )}
          </>
        ) : entry.reference_type === "document" ? (
          // A document without a partner is the gap a recall asks about; a
          // production run or a count never had one, and saying so is noise.
          <span className="text-on-muted italic">
            {t("inventory:lot.trace.noPartner")}
          </span>
        ) : null}
        <Made entry={entry} />
      </span>
      <span className="text-sm tabular-nums text-on whitespace-nowrap sm:text-right">
        {formatQuantityLocalized(t, formatDecimalQty(entry.quantity), uom)}
      </span>
    </li>
  );
}

function EntryList({
  heading,
  entries,
  uom,
  empty,
}: {
  heading: string;
  entries: LotTraceEntry[];
  uom: string | null | undefined;
  empty: string;
}) {
  return (
    <div>
      <div className="px-4 py-2 bg-surface-raised border-y border-border text-xs font-medium text-on-secondary uppercase tracking-wider">
        {heading}
      </div>
      {entries.length === 0 ? (
        <p className="px-4 py-3 text-sm text-on-secondary">{empty}</p>
      ) : (
        <ul className="divide-y divide-border">
          {entries.map((entry) => (
            <EntryRow
              key={`${entry.reference_type}-${entry.reference_id}`}
              entry={entry}
              uom={uom}
            />
          ))}
        </ul>
      )}
    </div>
  );
}

function LotSteps({
  lot,
  madeFromName,
}: {
  lot: LotTraceLot;
  madeFromName: string | null;
}) {
  const { t } = useTranslation("inventory");
  return (
    <Card className="p-0 overflow-hidden">
      {madeFromName && (
        <div className="px-4 py-3 text-sm text-on">
          {t("inventory:lot.trace.madeFrom", { lot: madeFromName })}{" "}
          <Link
            to={`/inventory/lots/${lot.lot_id}`}
            className="font-medium text-primary-600 hover:underline"
          >
            {lot.lot_name}
          </Link>
          {lot.product_name ? ` · ${lot.product_name}` : ""}
        </div>
      )}
      <EntryList
        heading={t("inventory:lot.trace.cameIn")}
        entries={lot.received ?? []}
        uom={lot.uom_symbol}
        empty={t("inventory:lot.trace.nothingCameIn")}
      />
      <EntryList
        heading={t("inventory:lot.trace.wentOut")}
        entries={lot.sent ?? []}
        uom={lot.uom_symbol}
        empty={t("inventory:lot.trace.nothingWentOut")}
      />
    </Card>
  );
}

export function LotTrace({ lotId }: { lotId: string }) {
  const { t } = useTranslation(["inventory", "common"]);
  const { data: trace, isLoading, isError, refetch } = useLotTrace(lotId);

  const handleExport = useCallback(async () => {
    try {
      toast.loading(t("common:actions.exporting"), { id: "lot-trace-export" });
      const blob = await stockLotsApi.exportTrace(lotId);
      downloadBlob(blob, `batch_trace_${getTodayFilename()}.xlsx`);
      toast.success(t("common:actions.exportSuccess"), {
        id: "lot-trace-export",
      });
    } catch (error) {
      toast.error(extractApiError(error, t("common:actions.exportError")), {
        id: "lot-trace-export",
      });
    }
  }, [lotId, t]);

  const names = new Map(
    (trace?.lots ?? []).map((lot) => [lot.lot_id, lot.lot_name]),
  );

  return (
    <section aria-labelledby="lot-trace-heading">
      <div className="flex flex-wrap items-center justify-between gap-3 mb-2 px-1">
        <h2 id="lot-trace-heading" className="text-lg font-semibold text-on">
          {t("inventory:lot.trace.heading")}
        </h2>
        <Button
          variant="outline"
          size="sm"
          onClick={() => void handleExport()}
          leftIcon={<FileDown size={16} />}
          disabled={!trace}
        >
          {t("common:actions.export")}
        </Button>
      </div>
      <p className="text-sm text-on-secondary mb-4 px-1">
        {t("inventory:lot.trace.caption")}
      </p>
      {isLoading ? (
        <LoadingSpinner />
      ) : isError || !trace ? (
        <QueryError onRetry={() => void refetch()} />
      ) : (
        <div className="space-y-4">
          {trace.lots.map((lot) => (
            <LotSteps
              key={lot.lot_id}
              lot={lot}
              madeFromName={
                lot.made_from_lot_id
                  ? (names.get(lot.made_from_lot_id) ?? null)
                  : null
              }
            />
          ))}
          {trace.truncated && (
            <Card className="p-4 text-sm text-on-secondary">
              {t("inventory:lot.trace.truncated")}
            </Card>
          )}
        </div>
      )}
    </section>
  );
}
