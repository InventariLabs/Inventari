/**
 * StockLotPage — /inventory/lots/:id
 *
 * The screen a warehouse opens once a year, on the day a supplier recalls a
 * batch, and that decides on that day whether the system was worth its
 * money: what this batch is, what state it is in, how much of it is still
 * standing and where, and everything that ever happened to it.
 *
 * Two records side by side on purpose. What is left comes from the shelf
 * (the quants); the trail below comes from the ledger. They are kept apart
 * because they are independent, and a reader who sees them disagree has
 * learned something a single derived number would have hidden.
 */
import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { Card } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { ActionMenu } from "@/components/ui/ActionMenu";
import LoadingSpinner from "@/components/LoadingSpinner";
import { QueryError } from "@/components/ui/QueryResult";
import { RecordNotFound } from "@/components/ui/RecordNotFound";
import { isNotFoundError } from "@/lib/errors";
import { formatDate } from "@/utils/formatters";
import { formatDecimalQty } from "@/utils/formatters";
import { formatQuantityLocalized } from "@/lib/i18nHelpers";
import { useModulePageHeader } from "@/hooks/useModulePageHeader";
import { useCanWrite } from "@/hooks/useCanWrite";
import { useStockLot } from "../hooks/useStockLot";
import { useSetLotStatus } from "../hooks/useStockLots";
import {
  LotStatusDialog,
  type LotStatusRequest,
} from "../components/lots/LotStatusDialog";
import type { LotStatus } from "@/lib/api/stockLots";
import { RecentStockMoves } from "../components/moves/RecentStockMoves";

/** Held, quarantined and recalled all mean "do not ship it" — say which. */
const STATUS_TONE: Record<string, "success" | "warning" | "danger"> = {
  active: "success",
  quarantined: "warning",
  held: "warning",
  expired: "danger",
  recalled: "danger",
};

const STATUSES: LotStatus[] = [
  "active",
  "quarantined",
  "held",
  "expired",
  "recalled",
];

function Field({ label, value }: { label: string; value: string | null }) {
  if (!value) return null;
  return (
    <div className="py-3 border-b border-border">
      <dt className="text-xs font-medium text-on-muted uppercase tracking-wide">
        {label}
      </dt>
      <dd className="mt-1 text-sm text-on break-words">{value}</dd>
    </div>
  );
}

export default function StockLotPage() {
  const { id } = useParams<{ id: string }>();
  const { t } = useTranslation(["inventory", "common"]);
  const { setHeader } = useModulePageHeader();
  const [pending, setPending] = useState<LotStatusRequest | null>(null);
  const setStatus = useSetLotStatus();

  // Holding a batch back is a stock write, the same as the list row.
  const canWrite = useCanWrite("items");

  const {
    data: lot,
    isLoading,
    isError,
    error,
    refetch,
  } = useStockLot(id ?? "");

  useEffect(() => {
    if (!lot) return;
    setHeader({
      title: lot.name,
      subtitle: lot.product_name ?? undefined,
      backTo: "/inventory/lots",
      // The decision belongs on the card: the reader has just seen where the
      // batch still lies and what happened to it. It used to live only in the
      // list row, so acting on a recall meant going back and finding the row.
      actions: canWrite ? (
        <ActionMenu
          label={t("inventory:lots.actionsFor", { name: lot.name })}
          actions={STATUSES.filter((value) => value !== lot.status).map(
            (value) => ({
              id: value,
              label: t(`inventory:lots.setTo.${value}`),
              onSelect: () =>
                setPending({ lotId: lot.id, lotName: lot.name, status: value }),
            }),
          )}
        />
      ) : undefined,
    });
    return () => setHeader({});
  }, [lot, setHeader, t, canWrite]);

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

  if (isLoading) return <LoadingSpinner />;

  if (isError && !isNotFoundError(error)) {
    return <QueryError onRetry={() => void refetch()} />;
  }

  if (!lot) {
    return (
      <RecordNotFound
        title={t("inventory:lot.notFound")}
        backTo="/inventory/lots"
        backLabel={t("inventory:lot.backToLots")}
      />
    );
  }

  const quantity = (value: string | number) =>
    formatQuantityLocalized(t, formatDecimalQty(value), lot.uom_symbol);

  return (
    <div className="space-y-6">
      <Card className="p-6 space-y-5">
        <div className="flex flex-wrap items-center gap-3">
          <Badge variant={STATUS_TONE[lot.status] ?? "secondary"}>
            {t(`inventory:lot.status.${lot.status}`, {
              defaultValue: lot.status,
            })}
          </Badge>
          {/* Why, next to what. This is the screen somebody opens on the day
              of a recall, and "quarantined" without the notice number is the
              half of the answer they did not come for. */}
          {lot.status_reason && (
            <span className="text-sm text-on-secondary break-words">
              {lot.status_reason}
            </span>
          )}
          {/* The number a recall notice is about, and the number the
              warehouse has to act on, in the same line. */}
          <span className="text-sm text-on-secondary">
            {t("inventory:lot.onHand")}:{" "}
            <span className="font-medium text-on tabular-nums">
              {quantity(lot.on_hand)}
            </span>
          </span>
        </div>

        {/* The product is the page's subtitle already -- repeating it as the
            first row pushes the dates, which are the reason anyone opened
            this screen, below the fold. */}
        <dl className="grid grid-cols-1 sm:grid-cols-2 gap-x-10">
          <Field
            label={t("inventory:lot.fields.expiry")}
            value={lot.expiry_date ? formatDate(lot.expiry_date) : null}
          />
          <Field
            label={t("inventory:lot.fields.production")}
            value={lot.production_date ? formatDate(lot.production_date) : null}
          />
          <Field
            label={t("inventory:lot.fields.useBy")}
            value={lot.use_by_date ? formatDate(lot.use_by_date) : null}
          />
          <Field
            label={t("inventory:lot.fields.kind")}
            value={
              lot.is_serial
                ? t("inventory:lot.serial")
                : t("inventory:lot.batch")
            }
          />
        </dl>
      </Card>

      <section>
        <h2 className="text-lg font-semibold text-on mb-4 px-1">
          {t("inventory:lot.whereHeading")}
        </h2>
        {lot.locations.length === 0 ? (
          // Not an error and not a gap: a batch that has been fully shipped
          // is the normal end of a batch's life, and the trail below is
          // exactly what a recall then asks for.
          <Card className="p-4 text-sm text-on-secondary">
            {t("inventory:lot.nothingLeft")}
          </Card>
        ) : (
          <Card className="p-0 overflow-hidden">
            <ul className="divide-y divide-border">
              {lot.locations.map((place) => (
                <li
                  key={place.location_id}
                  className="flex items-center justify-between gap-4 px-4 py-3"
                >
                  <span className="text-sm text-on">
                    {place.location_name ?? "—"}
                  </span>
                  <span className="text-sm tabular-nums text-on whitespace-nowrap">
                    {quantity(place.quantity)}
                  </span>
                </li>
              ))}
            </ul>
          </Card>
        )}
      </section>

      <section>
        <h2 className="text-lg font-semibold text-on mb-4 px-1">
          {t("inventory:lot.trailHeading")}
        </h2>
        {/* The decisions come first: a quarantine with its reason, author
            and day is what a recall reader came for, and the movement
            ledger never held it — it lives on the batch itself. */}
        {lot.status_history.length > 0 && (
          <Card className="p-0 overflow-hidden mb-4">
            <div className="px-4 py-3 bg-surface-raised border-b border-border text-xs font-medium text-on-secondary uppercase tracking-wider">
              {t("inventory:lot.decisionsHeading")}
            </div>
            <ul className="divide-y divide-border">
              {lot.status_history.map((entry, index) => (
                <li
                  key={`${entry.at ?? "undated"}-${entry.status}-${index}`}
                  className="px-4 py-3 flex flex-wrap items-center gap-x-3 gap-y-1"
                >
                  <span className="text-sm tabular-nums text-on-secondary whitespace-nowrap">
                    {entry.at ? formatDate(entry.at) : "—"}
                  </span>
                  <Badge variant={STATUS_TONE[entry.status] ?? "secondary"}>
                    {t(`inventory:lot.status.${entry.status}`, {
                      defaultValue: entry.status,
                    })}
                  </Badge>
                  {entry.reason && (
                    <span className="text-sm text-on break-words">
                      {entry.reason}
                    </span>
                  )}
                  {entry.by_name && (
                    <span className="text-sm text-on-secondary">
                      {entry.by_name}
                    </span>
                  )}
                </li>
              ))}
            </ul>
          </Card>
        )}
        <RecentStockMoves
          showProduct={false}
          filters={{ lot_id: lot.id }}
          caption={t("inventory:lot.trailCaption")}
          emptyTitle={t("inventory:lot.empty.title")}
          emptyDescription={t("inventory:lot.empty.description")}
        />
      </section>

      <LotStatusDialog
        request={pending}
        onConfirm={change}
        onCancel={() => setPending(null)}
      />
    </div>
  );
}
