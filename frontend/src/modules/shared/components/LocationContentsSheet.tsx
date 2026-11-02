/**
 * What is on a scanned location label — the answer to "what is on this
 * shelf, and how much".
 *
 * A location label used to do one thing: set the scan context. A rack whose
 * stock stands on its shelves told the reader nothing, because the location
 * page lists only what lies on the location itself. This sheet asks the
 * shelves instead (`/stock-quants` answers for the whole subtree) and offers
 * what a person standing at the rack does next.
 */
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import {
  ArrowRightLeft,
  ClipboardCheck,
  ExternalLink,
  Pin,
  Printer,
} from "lucide-react";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { EmptyState } from "@/components/ui/EmptyState";
import { QueryError } from "@/components/ui/QueryResult";
import {
  Sheet,
  SheetActions,
  SheetBody,
  SheetFooter,
  SheetHeader,
} from "@/components/ui/Sheet";
import LoadingSpinner from "@/components/LoadingSpinner";
import { useModules } from "@/contexts/ModulesContext";
import { useCanWrite } from "@/hooks/useCanWrite";
import { queryKeys } from "@/hooks/queries/keys";
import { useOfferedLocations } from "@/module-sdk";
import { stockQuantsApi } from "@/lib/api/stockQuants";
import { formatQuantityLocalized } from "@/lib/i18nHelpers";
import { formatDate, getExpiryState } from "@/utils/helpers";
import { formatDecimalQty } from "@/utils/formatters";
import { useStorageLocationLabels } from "../hooks/useStorageLocationLabels";
import { BarcodeLabelSheet } from "./BarcodeLabelSheet";

/** Lines shown before the sheet sends the reader to the location page. */
const LINES = 100;

interface LocationContentsSheetProps {
  location: { id: string; name: string };
  onClose: () => void;
  /** Offered where the screen keeps a scan context to point at the place. */
  onUseAsContext?: () => void;
  /** Offered where a torn or missing sticker is the next job: prints this
   *  place's label from the sheet. */
  offerLabel?: boolean;
}

export function LocationContentsSheet({
  location,
  onClose,
  onUseAsContext,
  offerLabel,
}: LocationContentsSheetProps) {
  const { t } = useTranslation(["scan", "common", "inventory"]);
  const navigate = useNavigate();
  const { isModuleEnabled } = useModules();
  const canMove = useCanWrite("locations");
  const mayCount = useCanWrite("stock_takes") && isModuleEnabled("stock_takes");
  // A stock take counts where stock flows go, and its picker leaves out the
  // places a module owns: a count started on one opened a form whose
  // location field could not show the place it came from. The button waits
  // for the same answer the picker gives.
  const countable = useOfferedLocations([location.id], { enabled: mayCount });
  const canCount = mayCount && !!countable.data?.includes(location.id);
  const [printing, setPrinting] = useState(false);

  const filters = { location_id: location.id, limit: LINES };
  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: queryKeys.stockQuants.list(filters),
    queryFn: () => stockQuantsApi.list(filters),
  });
  const rows = data?.items ?? [];
  const hidden = (data?.total ?? 0) - rows.length;
  const placeName = useStorageLocationLabels([
    location.id,
    ...rows.map((row) => row.location_id),
  ]);

  const go = (target: string) => () => navigate(target);
  const path = placeName(location.id, location.name) ?? location.name;

  return (
    <Sheet open onClose={onClose} backdropOpacity={60} aria-label={path}>
      <SheetHeader title={location.name} onClose={onClose} />
      {path !== location.name && (
        <p className="px-5 pt-3 text-xs text-on-muted">{path}</p>
      )}

      <SheetBody className="p-4">
        {isLoading ? (
          <LoadingSpinner />
        ) : isError ? (
          <QueryError onRetry={() => refetch()} />
        ) : rows.length === 0 ? (
          <EmptyState title={t("scan:locationSheet.empty")} />
        ) : (
          <ul className="divide-y divide-border">
            {rows.map((row) => {
              const state = getExpiryState(row.expiry_date);
              const place =
                row.location_id === location.id
                  ? null
                  : placeName(row.location_id, row.location_name);
              return (
                <li
                  key={row.id}
                  className="flex items-start justify-between gap-3 py-2.5"
                >
                  <div className="min-w-0">
                    <p className="font-medium text-on">
                      {row.product_name ?? "—"}
                    </p>
                    <p className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-on-muted">
                      {[place, row.lot_name].filter(Boolean).join(" · ")}
                      {row.expiry_date && (
                        <Badge
                          variant={
                            state === "expired"
                              ? "danger"
                              : state === "expiring"
                                ? "warning"
                                : "secondary"
                          }
                          data-expiry-state={state}
                        >
                          {t("scan:locationSheet.until", {
                            date: formatDate(row.expiry_date),
                          })}
                        </Badge>
                      )}
                      {row.lot_status && row.lot_status !== "active" && (
                        <Badge variant="warning">
                          {t(`inventory:lot.status.${row.lot_status}`, {
                            defaultValue: row.lot_status,
                          })}
                        </Badge>
                      )}
                    </p>
                  </div>
                  <span className="tabular-nums text-on whitespace-nowrap">
                    {formatQuantityLocalized(
                      t,
                      formatDecimalQty(row.quantity),
                      row.uom_symbol,
                    )}
                  </span>
                </li>
              );
            })}
          </ul>
        )}
        {hidden > 0 && (
          <p className="pt-3 text-xs text-on-muted">
            {t("scan:locationSheet.more", { hidden })}
          </p>
        )}
      </SheetBody>

      <SheetFooter>
        <SheetActions className="grid grid-cols-2 sm:flex sm:flex-wrap">
          {onUseAsContext && (
            <Button
              variant="outline"
              leftIcon={<Pin size={16} />}
              onClick={() => {
                onUseAsContext();
                onClose();
              }}
            >
              {t("scan:locationSheet.useAsContext")}
            </Button>
          )}
          <Button
            variant="outline"
            leftIcon={<ExternalLink size={16} />}
            onClick={go(`/inventory/locations/${location.id}`)}
          >
            {t("scan:locationSheet.open")}
          </Button>
          {offerLabel && (
            <Button
              variant="outline"
              leftIcon={<Printer size={16} />}
              onClick={() => setPrinting(true)}
            >
              {t("scan:locationSheet.printLabel")}
            </Button>
          )}
          {canCount && (
            <Button
              variant="outline"
              leftIcon={<ClipboardCheck size={16} />}
              onClick={go(`/inventory/stock-takes?new=${location.id}`)}
            >
              {t("scan:locationSheet.stockTake")}
            </Button>
          )}
          {canMove && (
            <Button
              variant="outline"
              leftIcon={<ArrowRightLeft size={16} />}
              // Move is a promise about one field, so the address says which
              // one the edit sheet should land on.
              onClick={go(
                `/inventory/locations/${location.id}?configure=true&focus=move`,
              )}
            >
              {t("scan:locationSheet.move")}
            </Button>
          )}
        </SheetActions>
      </SheetFooter>
      {printing && (
        <BarcodeLabelSheet
          target={{ storageIds: [location.id] }}
          onClose={() => setPrinting(false)}
        />
      )}
    </Sheet>
  );
}
