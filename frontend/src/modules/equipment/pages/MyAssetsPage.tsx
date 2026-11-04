import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import {
  Monitor,
  Clock,
  ShieldCheck,
  ChevronRight,
  History,
  Info,
  RotateCcw,
} from "lucide-react";
import { useModulePageHeader } from "@/hooks/useModulePageHeader";
import { useCanWrite } from "@/hooks/useCanWrite";
import { Card } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { AssetStatusBadge } from "@/modules/equipment/components/AssetStatusBadge";
import { CheckinModal } from "@/modules/equipment/components/CheckinModal";
import {
  useMyAssets,
  useMyAssetHistory,
} from "@/modules/equipment/hooks/useMyAssets";
import LoadingSpinner from "@/components/LoadingSpinner";
import { QueryError } from "@/components/ui/QueryResult";
import { formatDate } from "@/utils/helpers";
import { useFormatOrgDay } from "@/hooks/useOrganizationTimezone";
import { getCategoryLabel } from "@/modules/equipment/components/assetUtils";

export default function MyAssetsPage() {
  const { t } = useTranslation("equipment");
  const { setHeader } = useModulePageHeader();
  const [showHistory, setShowHistory] = useState(false);
  // Checking in is `equipment:write` on the API, and it is the right key: a
  // return is somebody receiving the unit back and recording its condition,
  // not the holder declaring it gone. So the holder who does hold the key
  // gets the action here, and the holder who does not gets told who does —
  // rather than a screen that ends at reading with no word about why.
  const canWrite = useCanWrite("equipment");
  const [returning, setReturning] = useState<{
    id: string;
    item_name: string;
    holder_name?: string | null;
    holder_kind?: "person" | "location" | null;
  } | null>(null);

  const { data: assets = [], isLoading, isError, refetch } = useMyAssets();
  // The return day is pinned to the organization's calendar, so it prints
  // in the card's own medium style on the org's clock.
  const formatReturnDay = useFormatOrgDay("medium");
  const {
    data: history = [],
    isLoading: historyLoading,
    isError: historyError,
    refetch: refetchHistory,
  } = useMyAssetHistory();

  useEffect(() => {
    setHeader({
      title: t("my_assets.title", "My Assets"),
      subtitle: t("my_assets.subtitle", "Assets currently assigned to you"),
    });
  }, [setHeader, t]);

  if (isError) {
    return <QueryError onRetry={() => refetch()} />;
  }

  if (isLoading) {
    return <LoadingSpinner />;
  }

  return (
    <div className="space-y-6">
      {assets.length === 0 ? (
        <Card className="p-8 text-center">
          <Monitor size={48} className="text-on-muted/40 mb-4 mx-auto" />
          <h3 className="text-lg font-semibold text-on mb-1">
            {t("my_assets.empty", "No assets assigned to you")}
          </h3>
          <p className="text-sm text-on-muted">
            {t(
              "my_assets.empty_hint",
              "Assets checked out to you will appear here.",
            )}
          </p>
        </Card>
      ) : (
        <div className="space-y-3">
          {assets.map((asset) => (
            <Card
              key={asset.assignment_id}
              className="p-4 hover:bg-surface-secondary transition-colors group"
            >
              <div className="flex items-start gap-2">
                <Link
                  to={`/equipment/${asset.item_id}`}
                  className="flex flex-1 min-w-0 items-start gap-4 cursor-pointer"
                >
                  {(asset.image_url ?? asset.model_image_url) ? (
                    <img
                      src={asset.image_url ?? asset.model_image_url ?? ""}
                      alt={asset.item_name}
                      loading="lazy"
                      className="h-12 w-12 rounded-lg object-cover flex-shrink-0"
                    />
                  ) : (
                    <div className="h-12 w-12 rounded-lg bg-surface-secondary flex items-center justify-center flex-shrink-0">
                      <Monitor size={20} className="text-on-muted" />
                    </div>
                  )}
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 mb-1">
                      <h4 className="text-sm font-medium truncate">
                        {asset.item_name}
                      </h4>
                      <AssetStatusBadge status={asset.equipment_status} />
                    </div>
                    <div className="flex items-center gap-3 text-xs text-on-muted">
                      {asset.category_name && (
                        <span>
                          {getCategoryLabel(t, {
                            code: asset.category_code,
                            name: asset.category_name,
                          })}
                        </span>
                      )}
                      {asset.serial_number && (
                        <span>SN: {asset.serial_number}</span>
                      )}
                    </div>
                    <div className="flex items-center gap-4 mt-2 text-xs text-on-muted">
                      <span className="flex items-center gap-1">
                        <Clock size={12} />
                        {t("my_assets.checked_out", "Checked out")}{" "}
                        {formatDate(asset.checked_out_at)}
                      </span>
                      {asset.expected_return_at && (
                        <span className="flex items-center gap-1">
                          {new Date(asset.expected_return_at) < new Date()
                            ? t("my_assets.overdue", "Overdue")
                            : t("my_assets.due", "Due")}{" "}
                          {formatReturnDay(asset.expected_return_at)}
                        </span>
                      )}
                      {asset.warranty_until && (
                        <span className="flex items-center gap-1">
                          <ShieldCheck size={12} />
                          {t("my_assets.warranty", "Warranty")}{" "}
                          {formatDate(asset.warranty_until)}
                        </span>
                      )}
                    </div>
                  </div>
                  <ChevronRight
                    size={16}
                    className="text-on-muted group-hover:text-on transition-colors flex-shrink-0 mt-2"
                  />
                </Link>
                {canWrite && (
                  <Button
                    variant="outline"
                    size="sm"
                    className="flex-shrink-0"
                    leftIcon={<RotateCcw size={14} />}
                    onClick={() =>
                      setReturning({
                        id: asset.assignment_id,
                        item_name: asset.item_name,
                        // The payload names the holder; this is the holder's
                        // own list, so a payload that does not reads "You"
                        // instead of leaving "Assigned to:" with no tail.
                        holder_name: asset.holder_name ?? t("assignments.you"),
                        holder_kind: asset.holder_kind,
                      })
                    }
                  >
                    {t("my_assets.return", "Return")}
                  </Button>
                )}
              </div>
            </Card>
          ))}
        </div>
      )}

      {assets.length > 0 && !canWrite && (
        <p className="flex items-start gap-2 text-xs text-on-muted">
          <Info size={14} className="flex-shrink-0 mt-0.5" />
          {t(
            "my_assets.who_returns",
            "A return is recorded by whoever receives the unit back — ask the person who looks after equipment to check it in, or to log a fault.",
          )}
        </p>
      )}

      <div className="flex items-center justify-between">
        <h3 className="text-sm font-medium text-on-muted flex items-center gap-2">
          <History size={14} />
          {t("my_assets.history_title", "Assignment History")}
        </h3>
        <Button
          variant="ghost"
          size="sm"
          onClick={() => setShowHistory(!showHistory)}
        >
          {showHistory
            ? t("my_assets.hide_history", "Hide")
            : t("my_assets.show_history", "Show")}
        </Button>
      </div>

      {showHistory && (
        <>
          {historyError ? (
            <QueryError onRetry={() => refetchHistory()} />
          ) : historyLoading ? (
            <LoadingSpinner />
          ) : history.length === 0 ? (
            <p className="text-xs text-on-muted text-center py-4">
              {t("my_assets.no_history", "No past assignments")}
            </p>
          ) : (
            <div className="space-y-2">
              {history.map((h) => (
                <div
                  key={h.assignment_id}
                  className="flex items-center justify-between text-sm px-2 py-2 border-b border-border last:border-0"
                >
                  <div>
                    <Link
                      to={`/equipment/${h.item_id}`}
                      className="font-medium hover:underline"
                    >
                      {h.item_name}
                    </Link>
                    <p className="text-xs text-on-muted">
                      {formatDate(h.checked_out_at)} —{" "}
                      {h.checked_in_at ? formatDate(h.checked_in_at) : "..."}
                    </p>
                  </div>
                  {h.checkin_condition && (
                    <span className="text-xs text-on-muted">
                      {t(
                        `assignments.condition_${h.checkin_condition.toLowerCase()}`,
                        { defaultValue: h.checkin_condition },
                      )}
                    </span>
                  )}
                </div>
              ))}
            </div>
          )}
        </>
      )}

      {returning && (
        <CheckinModal
          assignment={returning}
          byHolder
          onClose={() => setReturning(null)}
        />
      )}
    </div>
  );
}
