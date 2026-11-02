import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useWebhookDeliveries } from "@/modules/webhooks/hooks/useWebhooks";
import {
  CheckCircle,
  XCircle,
  Clock,
  ChevronDown,
  ChevronUp,
} from "lucide-react";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { QueryError } from "@/components/ui/QueryResult";
import type { WebhookDelivery } from "@/modules/webhooks/types/webhooks";
import { formatDateTime, formatDateTimePrecise } from "@/utils/helpers";
import { cn } from "@/lib/utils";

/**
 * A target that answers with a full HTML page puts the whole document in the
 * delivery row. Enough of it to recognise the answer, not enough to bury the
 * log under someone else's page template.
 */
const MAX_BODY_CHARS = 600;

function shorten(text: string): string {
  return text.length > MAX_BODY_CHARS
    ? `${text.slice(0, MAX_BODY_CHARS)}…`
    : text;
}

interface Props {
  webhookId: string;
  /** Whether the endpoint is on; an off one skips events without a row. */
  isActive?: boolean;
}

function StatusBadge({
  status,
}: {
  status: WebhookDelivery["delivery_status"];
}) {
  const { t } = useTranslation("webhooks");
  if (status === "success") {
    return (
      <Badge variant="success">
        <CheckCircle className="w-3 h-3 mr-1 inline" />
        {t("delivery.success")}
      </Badge>
    );
  }
  if (status === "pending") {
    return (
      <Badge variant="info">
        <Clock className="w-3 h-3 mr-1 inline" />
        {t("delivery.pending")}
      </Badge>
    );
  }
  if (status === "pending_retry") {
    return (
      <Badge variant="warning">
        <Clock className="w-3 h-3 mr-1 inline" />
        {t("delivery.pendingRetry")}
      </Badge>
    );
  }
  return (
    <Badge variant="danger">
      <XCircle className="w-3 h-3 mr-1 inline" />
      {t("delivery.failed")}
    </Badge>
  );
}

// The row dates the attempt that produced its status, not the enqueue: a
// retry answering after minutes of backoff used to wear the enqueue time and
// read as a result that arrived before the event it describes. Seconds stay,
// because telling two attempts apart is still what this log is read for.
// Rows written before attempts were dated fall back to the enqueue time.

function abandonReasonText(t: (key: string) => string, reason: string): string {
  // Inline keys, not a composed one: the i18n gates read the literals here.
  switch (reason) {
    case "circuit_breaker":
      return t("delivery.abandon.circuitBreaker");
    case "webhook_disabled":
      return t("delivery.abandon.webhookDisabled");
    case "webhook_deleted":
      return t("delivery.abandon.webhookDeleted");
    case "module_disabled":
      return t("delivery.abandon.moduleDisabled");
    default:
      return reason;
  }
}

function DeliveryRow({ delivery }: { delivery: WebhookDelivery }) {
  const { t } = useTranslation("webhooks");
  const [expanded, setExpanded] = useState(false);

  const ts = formatDateTimePrecise(
    delivery.last_attempt_at ?? delivery.created_at,
  );

  return (
    <div className="border border-border rounded-lg overflow-hidden">
      <Button
        size="content"
        variant="ghost"
        onClick={() => setExpanded((v) => !v)}
        className="w-full justify-start py-3 px-4"
      >
        <span className="font-mono text-xs text-on-secondary dark:text-on-muted min-w-32">
          {delivery.event_type}
        </span>
        <StatusBadge status={delivery.delivery_status} />
        {delivery.status_code && (
          <span className="text-xs text-on-secondary dark:text-on-muted">
            HTTP {delivery.status_code}
          </span>
        )}
        <span className="text-xs text-on-muted dark:text-on-secondary ml-auto shrink-0">
          {ts}
        </span>
        {expanded ? (
          <ChevronUp className="w-4 h-4 text-on-muted shrink-0" />
        ) : (
          <ChevronDown className="w-4 h-4 text-on-muted shrink-0" />
        )}
      </Button>

      {expanded && (
        <div className="border-t border-border px-4 py-3 space-y-3 bg-surface">
          {delivery.abandon_reason && (
            <div>
              {/* An abandonment is Inventari's own stop — nobody answered, so
                  the row carries the translated reason and no status code.
                  Printing our refusal under "Response from the target" sent
                  the reader looking for the fault on the receiver's side. */}
              <p className="text-xs font-medium text-red-600 dark:text-red-400 mb-1">
                {t("delivery.abandonedByApp")}
              </p>
              <pre className="text-xs text-red-700 dark:text-red-300 bg-red-50 dark:bg-red-900/20 rounded p-2 overflow-x-auto whitespace-pre-wrap">
                {abandonReasonText(t, delivery.abandon_reason)}
              </pre>
            </div>
          )}
          {delivery.delivery_id && (
            <p className="text-xs text-on-secondary dark:text-on-muted break-all">
              <span className="font-medium">{t("delivery.deliveryId")}: </span>
              <span className="font-mono">{delivery.delivery_id}</span>
            </p>
          )}
          {delivery.error_message && (
            <div>
              {/* A status code means the target answered — what follows is its
                  reply, not our failure. Labelling a 405 page "Error" sent the
                  reader looking for the cause inside someone else's HTML. */}
              <p
                className={cn(
                  "text-xs font-medium mb-1",
                  delivery.status_code
                    ? "text-on-secondary dark:text-on-muted"
                    : "text-red-600 dark:text-red-400",
                )}
              >
                {delivery.status_code
                  ? t("delivery.targetResponse")
                  : t("delivery.error")}
              </p>
              <pre
                className={cn(
                  "text-xs rounded p-2 overflow-x-auto whitespace-pre-wrap",
                  delivery.status_code
                    ? "text-on-secondary bg-surface-card border border-border"
                    : "text-red-700 dark:text-red-300 bg-red-50 dark:bg-red-900/20",
                )}
              >
                {shorten(delivery.error_message)}
              </pre>
              {delivery.error_message.length > MAX_BODY_CHARS && (
                <p className="text-[10px] text-on-muted mt-1">
                  {t("delivery.truncated")}
                </p>
              )}
            </div>
          )}
          {delivery.next_retry_at &&
            delivery.delivery_status === "pending_retry" && (
              <p className="text-xs text-on-secondary dark:text-on-muted">
                {t("delivery.nextRetry")}:{" "}
                {formatDateTime(delivery.next_retry_at)}
              </p>
            )}
          <div>
            <p className="text-xs font-medium text-on-secondary dark:text-on-muted mb-1">
              {t("delivery.payload")}
            </p>
            <pre className="text-xs text-on-secondary bg-surface-card border border-border rounded p-2 overflow-x-auto max-h-40">
              {JSON.stringify(delivery.payload_json, null, 2)}
            </pre>
          </div>
          {delivery.response_body && (
            <div>
              <p className="text-xs font-medium text-on-secondary dark:text-on-muted mb-1">
                {t("delivery.response")}
              </p>
              <pre className="text-xs text-on-secondary bg-surface-card border border-border rounded p-2 overflow-x-auto max-h-40">
                {shorten(delivery.response_body)}
              </pre>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

const PAGE_SIZE = 20;

export default function WebhookDeliveryLogs({
  webhookId,
  isActive = true,
}: Props) {
  const { t } = useTranslation("webhooks");
  const [cursor, setCursor] = useState<string | null>(null);
  const [cursorHistory, setCursorHistory] = useState<(string | null)[]>([null]);

  const { data, isLoading, isError, refetch } = useWebhookDeliveries(
    webhookId,
    cursor,
    PAGE_SIZE,
  );

  const items = data?.items ?? [];
  const hasMore = data?.has_more ?? false;
  const nextCursor = data?.next_cursor ?? null;
  const pageIndex = cursorHistory.indexOf(cursor);

  const goNext = () => {
    if (nextCursor) {
      const newHistory = [...cursorHistory];
      if (!newHistory.includes(nextCursor)) {
        newHistory.push(nextCursor);
      }
      setCursorHistory(newHistory);
      setCursor(nextCursor);
    }
  };

  const goPrev = () => {
    if (pageIndex > 0) {
      setCursor(cursorHistory[pageIndex - 1]);
    }
  };

  return (
    <div className="space-y-3">
      {!isActive && (
        <p className="text-xs text-on-secondary">{t("eventsWhileOff")}</p>
      )}
      {isLoading && (
        <div className="flex items-center justify-center py-8">
          <div className="w-5 h-5 border border-primary-500 border-t-transparent rounded-full animate-spin" />
        </div>
      )}

      {isError && <QueryError onRetry={() => void refetch()} />}

      {!isLoading && !isError && items.length === 0 && (
        <p className="text-sm text-on-secondary dark:text-on-muted py-4 text-center">
          {t("delivery.empty")}
        </p>
      )}

      {items.map((d: WebhookDelivery) => (
        <DeliveryRow key={d.id} delivery={d} />
      ))}

      {(pageIndex > 0 || hasMore) && (
        <div className="flex items-center justify-between pt-2">
          <p className="text-xs text-on-secondary dark:text-on-muted">
            {t("delivery.page", { page: pageIndex + 1 })}
          </p>
          <div className="flex gap-2">
            <Button
              size="sm"
              variant="secondary"
              disabled={pageIndex === 0}
              onClick={goPrev}
            >
              {t("pagination.prev")}
            </Button>
            <Button
              size="sm"
              variant="secondary"
              disabled={!hasMore}
              onClick={goNext}
            >
              {t("pagination.next")}
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
