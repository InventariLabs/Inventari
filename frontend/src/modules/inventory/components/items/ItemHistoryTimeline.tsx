import { useTranslation } from "react-i18next";
import {
  Plus,
  Pencil,
  ArrowRightLeft,
  TrendingUp,
  TrendingDown,
  Minus,
  Trash2,
  ArchiveRestore,
  LogOut,
  LogIn,
  FileText,
  Loader2,
  RefreshCw,
  PackageOpen,
} from "lucide-react";
import { useCallback } from "react";
import { Link } from "react-router-dom";
import { useItemDetailHistory } from "@/modules/inventory/hooks/useItems";
import { useEnabledModulesOptional } from "@/contexts/ModulesContext";
import { useHasPermission } from "@/hooks/useHasPermission";
import {
  parseChanges,
  type HistoryUnit,
} from "@/modules/inventory/utils/historyChanges";
import { useLocationsById } from "@/module-sdk";
import { formatDateTime } from "@/utils/formatters";
import { Button } from "@/components/ui/Button";
import type { ItemHistory } from "@/types";

interface ItemHistoryTimelineProps {
  itemId: string;
  /** The record's unit, so a row's numbers read "499 g", not "499". */
  unit?: HistoryUnit | null;
}

export const ACTION_CONFIG: Record<
  string,
  { icon: typeof Plus; color: string; labelKey: string }
> = {
  CREATED: {
    icon: Plus,
    color: "text-accent-600",
    labelKey: "history.actions.CREATED",
  },
  CREATED_VIA_SCAN: {
    icon: Plus,
    color: "text-accent-600",
    labelKey: "history.actions.CREATED_VIA_SCAN",
  },
  UPDATED: {
    icon: Pencil,
    color: "text-primary-600",
    labelKey: "history.actions.UPDATED",
  },
  MOVED: {
    icon: ArrowRightLeft,
    color: "text-primary-600",
    labelKey: "history.actions.MOVED",
  },
  TRANSFERRED: {
    icon: ArrowRightLeft,
    color: "text-primary-600",
    labelKey: "history.actions.TRANSFERRED",
  },
  QUANTITY_CHANGED: {
    icon: TrendingUp,
    color: "text-accent-600",
    labelKey: "history.actions.QUANTITY_CHANGED",
  },
  QUANTITY_INCREASED_VIA_SCAN: {
    icon: TrendingUp,
    color: "text-accent-600",
    labelKey: "history.actions.QUANTITY_INCREASED_VIA_SCAN",
  },
  OPENED: {
    icon: PackageOpen,
    color: "text-orange-500",
    labelKey: "history.actions.OPENED",
  },
  USED: {
    icon: Minus,
    color: "text-orange-500",
    labelKey: "history.actions.USED",
  },
  DISPOSED: {
    icon: Trash2,
    color: "text-red-600",
    labelKey: "history.actions.DISPOSED",
  },
  // The two actions that undo a mistake. Without a row here the header fell
  // back to the raw action name in capitals, beside "Quantity changed".
  DELETED: {
    icon: Trash2,
    color: "text-red-600",
    labelKey: "history.actions.DELETED",
  },
  RESTORED: {
    icon: ArchiveRestore,
    color: "text-accent-600",
    labelKey: "history.actions.RESTORED",
  },
  CHECKOUT: {
    icon: LogOut,
    color: "text-purple-600",
    labelKey: "history.actions.CHECKOUT",
  },
  CHECKIN: {
    icon: LogIn,
    color: "text-purple-600",
    labelKey: "history.actions.CHECKIN",
  },
  // The register's lifecycle transition is named by the word the asset
  // timeline already uses for it — one event, one name on both screens.
  STATUS_CHANGED: {
    icon: RefreshCw,
    color: "text-primary-600",
    labelKey: "equipment:timeline.status_changed",
  },
};

export function getQuantityChangeIcon(
  action: string,
  changes: Record<string, unknown> | null,
): { icon: typeof Plus; color: string; labelKey: string } {
  if (action === "QUANTITY_CHANGED" && changes) {
    // The API writes decimals as strings ("10.000"); compared as text,
    // "6.000" > "10.000". Read both as numbers.
    const oldQty = changes.old == null ? NaN : Number(changes.old);
    const newQty = changes.new == null ? NaN : Number(changes.new);
    if (!Number.isNaN(oldQty) && !Number.isNaN(newQty)) {
      if (newQty < oldQty) {
        return {
          icon: TrendingDown,
          color: "text-red-600",
          labelKey: "history.actions.QUANTITY_CHANGED",
        };
      }
      if (newQty > oldQty) {
        return {
          icon: TrendingUp,
          color: "text-accent-600",
          labelKey: "history.actions.QUANTITY_CHANGED",
        };
      }
    }
  }
  return (
    ACTION_CONFIG[action] ?? {
      icon: FileText,
      color: "text-on-secondary",
      labelKey: action,
    }
  );
}

function formatRelativeDate(
  dateStr: string,
  t: (key: string, opts?: Record<string, unknown>) => string,
  /** The interface language — the day is read, so it is written in it. */
  language: string,
): string {
  const date = new Date(dateStr);
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffMins = Math.floor(diffMs / 60000);
  const diffHours = Math.floor(diffMins / 60);
  const diffDays = Math.floor(diffHours / 24);

  if (diffMins < 1) return t("items:history.justNow");
  if (diffMins < 60) return t("items:history.minutesAgo", { count: diffMins });
  if (diffHours < 24) return t("items:history.hoursAgo", { count: diffHours });
  if (diffDays < 7) return t("items:history.daysAgo", { count: diffDays });
  // `undefined` here asked the browser for its language: the row said
  // "Jan 15" on a Polish screen whenever the browser was English.
  return date.toLocaleDateString(language, { month: "short", day: "numeric" });
}

interface HistoryEntryProps {
  entry: ItemHistory;
  locationName?: (id: string) => string | undefined;
  unit?: HistoryUnit | null;
}

function HistoryEntry({ entry, locationName, unit }: HistoryEntryProps) {
  const { t, i18n } = useTranslation("items");
  const config = getQuantityChangeIcon(entry.action, entry.changes);
  const Icon = config.icon;

  const changesDesc = parseChanges(
    entry.action,
    entry.changes,
    t,
    locationName,
    unit ?? undefined,
  );
  const relativeDate = formatRelativeDate(
    entry.created_at,
    t,
    i18n.language ?? "en",
  );
  const fullDate = formatDateTime(entry.created_at);

  return (
    <div className="flex gap-3 py-3">
      <div className="flex flex-col items-center">
        <div
          className={`flex h-8 w-8 items-center justify-center rounded-full bg-surface-card border border-border ${config.color}`}
        >
          <Icon size={14} />
        </div>
        <div className="w-px flex-1 bg-border mt-1" />
      </div>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-xs font-medium text-on">
            {t(config.labelKey, { defaultValue: entry.action })}
          </span>
          <span
            className="text-[10px] text-on-muted cursor-help"
            title={fullDate}
          >
            {relativeDate}
          </span>
        </div>
        {entry.user_name && (
          <p className="text-xs text-on-secondary mt-0.5">{entry.user_name}</p>
        )}
        {changesDesc && <p className="text-sm text-on mt-1">{changesDesc}</p>}
        {entry.source_document_id && (
          <SourceDocument
            documentId={entry.source_document_id}
            changes={entry.changes}
          />
        )}
      </div>
    </div>
  );
}

/**
 * The document behind the row, named and reachable.
 *
 * The row used to print eight hex characters of the document's id and three
 * dots, which is neither a name a person recognizes nor a string the document
 * search accepts — that field looks up numbers and references. Meanwhile the
 * same response already carries the number the document is filed under, and
 * for a correction the number of the document it corrects. History reads
 * forward everywhere in the application, document to stock; this is the way
 * back, and it is the direction a person actually walks: odd figure, then why.
 *
 * The number shows whatever happens. It becomes a link only where the link
 * leads somewhere: the module has to be enabled for the organization and the
 * account allowed to read documents, or following it would be a refusal
 * arriving after the click.
 */
function SourceDocument({
  documentId,
  changes,
}: {
  documentId: string;
  changes: Record<string, unknown> | null;
}) {
  const { t } = useTranslation("items");
  const enabledModules = useEnabledModulesOptional();
  const mayRead = useHasPermission("warehouse:read");

  const number =
    typeof changes?.document_number === "string"
      ? changes.document_number
      : undefined;
  const corrects =
    typeof changes?.corrects_document_number === "string"
      ? changes.corrects_document_number
      : undefined;
  const label = number ?? `${documentId.slice(0, 8)}...`;
  const reachable = enabledModules.includes("warehouse") && mayRead;

  return (
    <div className="mt-1 flex flex-wrap items-center gap-1">
      <FileText size={10} className="shrink-0 text-on-muted" />
      <span className="text-[10px] text-on-muted">
        {t("history.linkedDocument")}:
      </span>
      {reachable ? (
        <Link
          to={`/warehouse/documents/${documentId}`}
          className="text-[10px] text-on-primary hover:underline"
        >
          {label}
        </Link>
      ) : (
        <span className="text-[10px] text-on-muted">{label}</span>
      )}
      {corrects && (
        <span className="text-[10px] text-on-muted">
          {t("history.corrects", { number: corrects })}
        </span>
      )}
    </div>
  );
}

const ID_SHAPE =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** Every id-shaped string a row's changes mention, wherever it nests. */
function idsIn(value: unknown): string[] {
  if (typeof value === "string") return ID_SHAPE.test(value) ? [value] : [];
  if (Array.isArray(value)) return value.flatMap(idsIn);
  if (value && typeof value === "object") {
    return Object.values(value).flatMap(idsIn);
  }
  return [];
}

export default function ItemHistoryTimeline({
  itemId,
  unit,
}: ItemHistoryTimelineProps) {
  const { t } = useTranslation("items");
  const { data, fetchNextPage, hasNextPage, isFetchingNextPage, isLoading } =
    useItemDetailHistory(itemId);
  const entries = data?.pages.flatMap((p) => p.items) ?? [];

  // Names for MOVED rows: the ids the rows carry are read by id — virtual
  // and archived places included, a used-up record passes through them.
  // Any id the rows mention is asked about; the ones that are not places
  // (a category, a unit) simply come back unnamed.
  const { byId } = useLocationsById(
    entries.flatMap((entry) => idsIn(entry.changes)),
  );
  const locationName = useCallback((id: string) => byId.get(id)?.name, [byId]);

  if (isLoading) {
    return (
      <div className="flex justify-center py-8">
        <Loader2 size={20} className="animate-spin text-on-muted" />
      </div>
    );
  }

  if (entries.length === 0) {
    return (
      <div className="py-8 text-center">
        <p className="text-sm text-on-muted">{t("history.noEntries")}</p>
      </div>
    );
  }

  return (
    <div className="space-y-0">
      {entries.map((entry) => (
        <HistoryEntry
          key={entry.id}
          entry={entry}
          locationName={locationName}
          unit={unit}
        />
      ))}
      {hasNextPage && (
        <div className="flex justify-center py-3">
          <Button
            variant="outline"
            size="sm"
            onClick={() => fetchNextPage()}
            disabled={isFetchingNextPage}
          >
            {isFetchingNextPage ? (
              <Loader2 size={14} className="animate-spin" />
            ) : (
              t("history.loadMore")
            )}
          </Button>
        </div>
      )}
    </div>
  );
}
