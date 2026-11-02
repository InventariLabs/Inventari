import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import { Button } from "@/components/ui/Button";
import { CardLink } from "@/components/ui/CardLink";
import { Card } from "@/components/ui/Card";
import LoadingSpinner from "@/components/LoadingSpinner";
import { describeHistoryEntry } from "@/modules/warehouse/historyEntry";
import { useTodayActivity } from "@/modules/warehouse/hooks/useTodayActivity";
import type { WarehouseDocumentRow } from "@/modules/warehouse/types";
import type { TranslateFn } from "@/types/i18n";
import { cn } from "@/lib/utils";
import { formatTime } from "@/utils/formatters";

/**
 * One posting said the way a person would: who did it, what happened and the
 * document that proves it. The sentence comes from the History wording, so
 * the feed cannot describe the same posting differently from the page that
 * keeps every one of them; the actor is the one thing History shows in a
 * column and the feed has no column for.
 */
function entryText(doc: WarehouseDocumentRow, t: TranslateFn): string {
  const { sentence } = describeHistoryEntry(doc, t);
  const who = doc.completed_by_name ?? doc.created_by_name;
  return who ? t("start.feed.entry", { who, entry: sentence }) : sentence;
}

/**
 * Today's activity: the day's postings, newest first, each naming
 * the person and linking the document that proves it. A warehouse the reader
 * picked narrows the list to that place and its shelves; the server does the
 * narrowing so a busy day cannot push a warehouse's entries off the page.
 */
export function TodayActivity({
  warehouseId,
  className,
}: {
  warehouseId: string | null;
  className?: string;
}) {
  const { t } = useTranslation("warehouse");
  const { data, isLoading, isError, refetch } = useTodayActivity(warehouseId);
  const entries = data?.items ?? [];

  return (
    <Card className={cn("min-w-0 overflow-hidden p-0", className)}>
      <div className="flex flex-wrap items-center gap-2 border-b border-border px-4 py-3">
        <h2 className="text-base font-semibold text-on">
          {t("start.feed.title")}
        </h2>
        <span className="flex-1" />
        <CardLink to="/warehouse/history" arrow>
          {t("start.feed.history")}
        </CardLink>
      </div>
      {isLoading ? (
        <div className="flex justify-center py-8">
          <LoadingSpinner />
        </div>
      ) : isError ? (
        <p className="px-4 py-3 text-sm text-on-secondary">
          {t("start.feed.error")}{" "}
          <Button variant="link" size="inline" onClick={() => void refetch()}>
            {t("common:actions.retry")}
          </Button>
        </p>
      ) : entries.length === 0 ? (
        <p className="px-4 py-3 text-sm text-on-secondary">
          {t(warehouseId ? "start.feed.emptyWarehouse" : "start.feed.empty")}
        </p>
      ) : (
        <ol className="divide-y divide-border">
          {entries.map((doc) => (
            <li key={doc.id} className="flex gap-3 px-4 py-2.5">
              <span className="w-14 shrink-0 whitespace-nowrap pt-0.5 text-sm text-on-muted tabular-nums">
                {formatTime(doc.completed_at)}
              </span>
              <span className="flex min-w-0 flex-col gap-0.5">
                <span className="text-sm text-on">{entryText(doc, t)}</span>
                <Link
                  to={`/warehouse/documents/${doc.id}`}
                  className="break-all text-xs font-medium text-on-primary hover:underline"
                >
                  {doc.number}
                </Link>
              </span>
            </li>
          ))}
        </ol>
      )}
    </Card>
  );
}
