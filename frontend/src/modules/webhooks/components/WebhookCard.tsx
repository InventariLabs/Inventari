import { memo } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import {
  Trash2,
  Edit2,
  Activity,
  RefreshCw,
  XCircle,
  AlertTriangle,
  Send,
} from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import type { WebhookEndpoint } from "@/modules/webhooks/types/webhooks";
import { formatDateTime } from "@/utils/helpers";

function StatusDot({
  isActive,
  failures,
}: {
  isActive: boolean;
  failures: number;
}) {
  const { t } = useTranslation("webhooks");
  // An inactive card already says so in its badge, next to the dot; the two
  // live states had only a colour to tell them apart.
  if (!isActive) {
    return (
      <span className="flex h-2.5 w-2.5 shrink-0" aria-hidden="true">
        <span className="h-2.5 w-2.5 rounded-full bg-red-400" />
      </span>
    );
  }
  const failing = failures > 0;
  return (
    <span className="inline-flex items-center gap-1.5 text-xs text-on-secondary">
      <span className="relative flex h-2.5 w-2.5 shrink-0" aria-hidden="true">
        <span
          className={`animate-ping absolute inline-flex h-full w-full rounded-full opacity-75 ${failing ? "bg-yellow-400" : "bg-success-400"}`}
        />
        <span
          className={`relative inline-flex h-2.5 w-2.5 rounded-full ${failing ? "bg-yellow-500" : "bg-success-500"}`}
        />
      </span>
      {failing ? t("statusFailing") : t("statusActive")}
    </span>
  );
}

export const WebhookCard = memo(function WebhookCard({
  webhook,
  onEdit,
  onDelete,
  onTest,
  onReactivate,
  onLogs,
  isAdmin,
}: {
  webhook: WebhookEndpoint;
  onEdit: () => void;
  onDelete: () => void;
  onTest: () => void;
  onReactivate: () => void;
  onLogs: () => void;
  isAdmin: boolean;
}) {
  const { t } = useTranslation("webhooks");
  const autoDisabled = webhook.auto_disabled_at !== null;

  return (
    <Card className="p-4">
      <div className="flex flex-col gap-3 md:flex-row md:items-start">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <StatusDot
              isActive={webhook.is_active}
              failures={webhook.consecutive_failures}
            />
            <h3 className="text-sm font-semibold text-on dark:text-white truncate">
              {webhook.name}
            </h3>
            <Badge
              variant={webhook.http_method === "POST" ? "default" : "secondary"}
            >
              {webhook.http_method}
            </Badge>
            {!webhook.is_active && (
              <Badge variant="danger">
                <XCircle className="w-3 h-3 mr-1 inline" />
                {/* An endpoint somebody paused and one the breaker cut off
                    are both inactive; only the second may say why. */}
                {autoDisabled ? t("inactiveCircuitBreaker") : t("inactive")}
              </Badge>
            )}
            {/* Silent, not broken: every event it listens to belongs to a
                module that is off, so nothing will ever fire — yet the dot
                still reads active. Say so, or the card looks healthy. */}
            {webhook.events_all_module_disabled && (
              <Badge variant="warning">
                <AlertTriangle className="w-3 h-3 mr-1 inline" />
                {t("inactiveModuleDisabled")}
              </Badge>
            )}
            {/* The other half of the same silence: a name the catalogue no
                longer offers can never match an emission, and the list it
                disappeared from is the only place that used to say so. */}
            {webhook.events_unknown && (
              <Badge variant="warning">
                <AlertTriangle className="w-3 h-3 mr-1 inline" />
                {t("unknownEvents")}
              </Badge>
            )}
          </div>
          <p className="text-xs text-on-primary truncate mt-0.5">
            {webhook.url}
          </p>

          {autoDisabled && (
            <div className="flex items-start gap-1.5 mt-2 p-2 bg-yellow-50 dark:bg-yellow-900/20 rounded text-xs text-yellow-700 dark:text-yellow-300">
              <AlertTriangle className="w-3.5 h-3.5 shrink-0 mt-0.5" />
              <div className="min-w-0">
                <span>
                  {t("circuitBreakerWarning", {
                    count: webhook.consecutive_failures,
                  })}{" "}
                  {/* Events that fire while it is off are never stored, so
                      Reactivate cannot bring them back — say so here. */}
                  {t("eventsWhileOff")}{" "}
                  {/* The breaker knows that deliveries stopped, not why they
                      did — a refused signing secret, a timeout and a 500 all
                      land here. The cause of the last attempt is written on
                      its own log row; prescribing the URL pointed
                      administrators away from every cause but one. */}{" "}
                  <Button
                    variant="link"
                    size="contentSm"
                    onClick={onLogs}
                    className="underline font-medium px-0.5 min-h-11 md:min-h-0 min-w-11 md:min-w-0"
                  >
                    {t("logs")}
                  </Button>{" "}
                  {/* The threshold that cut this endpoint off lives two
                      screens away, and the card never said where. */}
                  <Link
                    to="/settings/modules/webhooks"
                    className="underline font-medium"
                  >
                    {t("thresholdLink")}
                  </Link>
                </span>
                {/* The way back belongs where the cut-off is announced: the
                    only other door is the edit form's last switch, under
                    forty event checkboxes. It is the card's only Reactivate
                    for a tripped endpoint (the action row below leaves its
                    own out), so a phone does not show the word twice. Its own
                    line, not `block` on the button: that overrode the
                    button's flex display and stacked the icon over the label. */}
                {isAdmin && (
                  <div className="mt-2">
                    <Button
                      variant="secondary"
                      size="sm"
                      onClick={onReactivate}
                      leftIcon={<RefreshCw className="w-3.5 h-3.5" />}
                      aria-label={`${t("reactivate")} ${webhook.name}`}
                    >
                      {t("reactivate")}
                    </Button>
                  </div>
                )}
              </div>
            </div>
          )}

          {/* Paused by a person, with deliveries that had been failing before
              that. The count is a fact worth carrying; what it caused is not
              this card's to say. */}
          {!webhook.is_active &&
            !autoDisabled &&
            webhook.consecutive_failures > 0 && (
              <p className="mt-2 text-xs text-on-muted">
                {t("failuresSinceSuccess", {
                  count: webhook.consecutive_failures,
                })}
              </p>
            )}

          {/* Event type chips */}
          <div className="flex flex-wrap gap-1 mt-2">
            {webhook.event_types.map((ev) => (
              <span
                key={ev}
                className="inline-flex items-center px-1.5 py-0.5 rounded text-xs font-mono bg-surface-raised text-on-secondary"
              >
                {ev}
              </span>
            ))}
          </div>

          {/* Stats row */}
          <div className="flex items-center gap-4 mt-2 text-xs text-on-secondary dark:text-on-muted">
            {webhook.last_triggered_at ? (
              <span className="flex items-center gap-1">
                <Activity className="w-3 h-3" />
                {formatDateTime(webhook.last_triggered_at)}
              </span>
            ) : (
              <span className="flex items-center gap-1">
                <Activity className="w-3 h-3" />
                {t("never")}
              </span>
            )}
            {webhook.last_status_code !== null && (
              <span
                className={
                  webhook.last_status_code >= 200 &&
                  webhook.last_status_code < 300
                    ? "text-on-success"
                    : "text-red-600 dark:text-red-400"
                }
              >
                HTTP {webhook.last_status_code}
              </span>
            )}
            {webhook.consecutive_failures > 0 && (
              <span className="text-yellow-600 dark:text-yellow-400">
                {t("consecutiveFailures")}: {webhook.consecutive_failures}
              </span>
            )}
          </div>
        </div>

        {/* Actions */}
        <div className="flex flex-wrap items-center gap-1 md:shrink-0 md:flex-nowrap border-t border-border pt-2 md:border-0 md:pt-0">
          <Button
            size="sm"
            variant="ghost"
            onClick={onLogs}
            title={t("logs")}
            aria-label={`${t("logs")} ${webhook.name}`}
          >
            <Activity className="w-4 h-4" />
            <span className="md:hidden ml-1.5">{t("logs")}</span>
          </Button>
          {isAdmin && (
            <>
              {!webhook.is_active && !autoDisabled && (
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={onReactivate}
                  title={t("reactivate")}
                  aria-label={`${t("reactivate")} ${webhook.name}`}
                  className="text-accent-600 dark:text-accent-400"
                >
                  <RefreshCw className="w-4 h-4" />
                  <span className="md:hidden ml-1.5">{t("reactivate")}</span>
                </Button>
              )}
              <Button
                size="sm"
                variant="ghost"
                onClick={onTest}
                title={t("testHint")}
                aria-label={`${t("test")} ${webhook.name}`}
              >
                <Send className="w-4 h-4" />
                <span className="md:hidden ml-1.5">{t("test")}</span>
              </Button>
              <Button
                size="sm"
                variant="ghost"
                onClick={onEdit}
                title={t("edit")}
                aria-label={`${t("edit")} ${webhook.name}`}
              >
                <Edit2 className="w-4 h-4" />
                <span className="md:hidden ml-1.5">{t("edit")}</span>
              </Button>
              <Button
                size="sm"
                variant="ghostDanger"
                onClick={onDelete}
                title={t("delete")}
                aria-label={`${t("delete")} ${webhook.name}`}
              >
                <Trash2 className="w-4 h-4" />
                <span className="md:hidden ml-1.5">{t("delete")}</span>
              </Button>
            </>
          )}
        </div>
      </div>
    </Card>
  );
});
