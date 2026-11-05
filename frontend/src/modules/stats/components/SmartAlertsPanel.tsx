import { Link } from "react-router-dom";
import { AlertTriangle, Clock, ShoppingCart, TrendingUp } from "lucide-react";
import type { SmartAlert, SmartAlerts } from "@/modules/stats/types/analytics";
import { Card } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { cn } from "@/lib/utils";
import { formatDate } from "@/utils/formatters";

interface SmartAlertsPanelProps {
  alerts: SmartAlerts;
  t: (key: string, opts?: Record<string, unknown>) => string;
}

const TYPE_TO_I18N_KEY: Record<string, string> = {
  forgotten_item: "forgotten",
  missing_staple: "staple",
  expiring_soon: "expiring",
  expired: "expired",
  low_stock: "lowStock",
};

type Translate = SmartAlertsPanelProps["t"];

// The backend names the sentence (`message_key`) and hands over its numbers;
// the words are the reader's language, so they are written here.
const alertMessage = (alert: SmartAlert, t: Translate): string => {
  const params = alert.message_params ?? {};
  switch (alert.message_key) {
    case "stats.alerts.forgotten_item":
      return t("stats:analytics.alerts.messages.forgotten", {
        count: params.days,
      });
    case "stats.alerts.missing_staple":
      return t("stats:analytics.alerts.messages.staple", {
        count: params.days_since,
      });
    // The date and how far off it is, in words: two records of one product
    // differ by their dates, and the colour alone never said which was the
    // urgent one.
    case "stats.alerts.expiring_soon": {
      const days = alert.days_until_expiry ?? 0;
      const date = formatDate(alert.expiry_date);
      return days > 0
        ? t("stats:analytics.alerts.messages.expiring", { date, count: days })
        : t("stats:analytics.alerts.messages.expiringToday", { date });
    }
    case "stats.alerts.expired":
      return t("stats:analytics.alerts.messages.expired", {
        date: formatDate(alert.expiry_date),
        count: Math.abs(alert.days_until_expiry ?? 0),
      });
    default:
      return "";
  }
};

// The record an alert is about, where it names one: the service sends
// `view_item` with the record's id, and a card that could not be opened left
// the reader to find the product by hand.
const alertHref = (alert: SmartAlert): string | null =>
  alert.action === "view_item" && alert.action_param
    ? `/inventory/items?open=${encodeURIComponent(alert.action_param)}`
    : null;

const getAlertIcon = (type: string) => {
  switch (type) {
    case "FORGOTTEN_ITEM":
      return <Clock className="w-5 h-5" />;
    case "MISSING_STAPLE":
      return <ShoppingCart className="w-5 h-5" />;
    case "EXPIRING_SOON":
    case "EXPIRED":
      return <AlertTriangle className="w-5 h-5" />;
    case "LOW_STOCK":
      return <TrendingUp className="w-5 h-5" />;
    default:
      return <AlertTriangle className="w-5 h-5" />;
  }
};

const getSeverityColor = (severity: string) => {
  switch (severity) {
    case "critical":
      return "bg-red-50 border-red-200 text-on-danger dark:bg-red-500/10 dark:border-red-500/20";
    case "high":
    case "medium":
    case "warning":
      return "bg-amber-50 border-amber-200 text-on-warning dark:bg-amber-500/10 dark:border-amber-500/20";
    case "low":
      return "bg-primary-50 border-primary-200 text-primary-700 dark:text-primary-500 dark:bg-primary-500/10 dark:border-primary-500/20";
    default:
      return "bg-surface-raised border-border text-on-secondary";
  }
};

function AlertName({ alert }: { alert: SmartAlert }) {
  const href = alertHref(alert);
  const className = "block font-semibold text-sm mb-1";
  return href ? (
    <Link
      to={href}
      className={cn(className, "min-h-6 underline-offset-2 hover:underline")}
    >
      {alert.item_name}
    </Link>
  ) : (
    <p className={className}>{alert.item_name}</p>
  );
}

export default function SmartAlertsPanel({ alerts, t }: SmartAlertsPanelProps) {
  return (
    <div className="space-y-6">
      {/* Summary */}
      <div className="grid grid-cols-2 gap-4">
        <Card className="p-5 border border-amber-200 bg-amber-50 dark:bg-amber-500/10 dark:border-amber-500/20">
          <div className="flex flex-col items-center text-center gap-2">
            <AlertTriangle className="w-6 h-6 text-on-warning" />
            <div>
              <p className="text-2xl font-semibold text-on">
                {alerts.total_alerts}
              </p>
              <p className="text-[10px] font-medium text-on-muted uppercase tracking-widest">
                {t("stats:analytics.alerts.total")}
              </p>
              <p className="mt-1 text-xs text-on-muted">
                {t("stats:analytics.alerts.totalHint")}
              </p>
            </div>
          </div>
        </Card>

        <Card className="p-5 border border-primary-200 bg-primary-50 dark:bg-primary-500/10 dark:border-primary-500/20">
          <div className="flex flex-col items-center text-center gap-2">
            <ShoppingCart className="w-6 h-6 text-primary-700 dark:text-primary-500" />
            <div>
              <p className="text-2xl font-semibold text-on">
                {
                  alerts.alerts.filter((a) => a.type === "FORGOTTEN_ITEM")
                    .length
                }
              </p>
              <p className="text-[10px] font-medium text-on-muted uppercase tracking-widest">
                {t("stats:analytics.alerts.types.forgotten")}
              </p>
              <p className="mt-1 text-xs text-on-muted">
                {t("stats:analytics.alerts.types.forgottenHint")}
              </p>
            </div>
          </div>
        </Card>
      </div>

      {/* Alerts List */}
      <div className="space-y-3">
        {alerts.alerts.map((alert, idx) => (
          <div
            key={idx}
            className={cn(
              "p-4 rounded-lg border transition-all",
              getSeverityColor(alert.severity),
            )}
          >
            <div className="flex items-start gap-3">
              <div className="flex-shrink-0 mt-0.5">
                {getAlertIcon(alert.type)}
              </div>
              <div className="flex-1 min-w-0">
                <AlertName alert={alert} />
                <p className="text-sm opacity-90">{alertMessage(alert, t)}</p>
              </div>
              <Badge
                variant={
                  alert.severity === "critical"
                    ? "danger"
                    : alert.severity === "high" ||
                        alert.severity === "medium" ||
                        alert.severity === "warning"
                      ? "warning"
                      : "info"
                }
              >
                {t(
                  `analytics.alerts.types.${TYPE_TO_I18N_KEY[alert.type.toLowerCase()] ?? alert.type.toLowerCase()}`,
                )}
              </Badge>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
