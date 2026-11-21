import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import {
  AlertTriangle,
  ArrowRightLeft,
  Hammer,
  ShoppingCart,
} from "lucide-react";
import { toast } from "sonner";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card, CardContent } from "@/components/ui/Card";
import { formatDecimalQty } from "@/utils/formatters";
import type { ReorderRule, ReplenishmentAlert } from "../api/reorder-rules";
import { useCreateReplenishmentDraftPos } from "../hooks/useReorderRules";

interface ReorderAlertsCardProps {
  alerts: ReplenishmentAlert[];
  locationName: (id: string) => string;
  canWrite?: boolean;
  /** The rules the alerts come from — they tell which supplier is the rule's own. */
  rules?: ReorderRule[];
}

export function ReorderAlertsCard({
  alerts,
  locationName,
  canWrite = false,
  rules = [],
}: ReorderAlertsCardProps) {
  const { t } = useTranslation("purchase_orders");
  const navigate = useNavigate();
  const draftMutation = useCreateReplenishmentDraftPos();

  // Only an alert with a supplier — the rule's own, or the one its price list
  // proposes — can become an order line; the rest are reported back by the
  // API, never made into empty orders.
  const actionableIds = alerts
    .filter((alert) => alert.preferred_partner_id)
    .map((alert) => alert.reorder_rule_id);

  const handleCreateDrafts = () => {
    draftMutation.mutate(actionableIds, {
      onSuccess: (result) => {
        if (result.created.length > 0) {
          toast.success(
            t("reorderRules.draftPosCreated", { count: result.created.length }),
          );
        }
        if (result.skipped.length > 0) {
          toast.info(
            t("reorderRules.draftPosSkipped", { count: result.skipped.length }),
          );
        }
      },
    });
  };

  return (
    <Card className="border-amber-300">
      <CardContent className="p-4">
        <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
          <div className="flex items-center gap-2 text-amber-700">
            <AlertTriangle size={16} />
            <h2 className="text-sm font-medium">
              {t("reorderRules.alertsTitle", { count: alerts.length })}
            </h2>
          </div>
          {canWrite && actionableIds.length > 0 && (
            <Button
              size="sm"
              leftIcon={<ShoppingCart size={16} />}
              onClick={handleCreateDrafts}
              isLoading={draftMutation.isPending}
            >
              {t("reorderRules.createDraftPos")}
            </Button>
          )}
        </div>
        <ul className="space-y-1 text-sm">
          {alerts.map((alert) => (
            <li
              key={alert.reorder_rule_id}
              className="flex flex-wrap items-center gap-x-2 text-on-secondary"
            >
              <span className="font-medium text-on">{alert.product_name}</span>
              {alert.sku && (
                <span className="text-xs text-on-muted">{alert.sku}</span>
              )}
              <span>
                {/* The alert fires under the higher of the two, so the card
                    names the one that stands higher. */}
                {alert.safety_stock > alert.min_quantity
                  ? t("reorderRules.alertStockSafety", {
                      available: alert.available_quantity,
                      threshold: alert.safety_stock,
                    })
                  : t("reorderRules.alertStock", {
                      available: alert.available_quantity,
                      min: alert.min_quantity,
                    })}
              </span>
              <span className="text-xs text-on-muted">
                {t("reorderRules.alertLocation", {
                  location: locationName(alert.location_id),
                })}
              </span>
              <span className="text-xs text-on-secondary">
                {t("reorderRules.reserveHolds", {
                  quantity: formatDecimalQty(alert.reserve_available_quantity),
                })}
              </span>
              <span className="text-xs text-on-secondary">
                {alert.make_instead
                  ? null
                  : alert.remaining_to_buy === 0
                    ? t("reorderRules.coveredByReserve")
                    : alert.remaining_to_buy != null &&
                      t("reorderRules.remainingToBuy", {
                        quantity: formatDecimalQty(alert.remaining_to_buy),
                      })}
              </span>
              {alert.proposed_move_quantity > 0 && canWrite && (
                <Button
                  size="sm"
                  variant="outline"
                  leftIcon={<ArrowRightLeft size={14} />}
                  onClick={() =>
                    navigate(
                      `/warehouse/todo?replenish=${alert.reorder_rule_id}`,
                    )
                  }
                >
                  {t("reorderRules.replenish")}
                </Button>
              )}
              {alert.make_instead ? (
                <MakeInsteadAction alert={alert} canWrite={canWrite} />
              ) : alert.preferred_partner_name ? (
                <span className="text-xs text-on-muted">
                  {/* A rule with no supplier of its own is proposed the
                      cheapest one on the price list; say so, because the
                      rules table beside it shows no supplier for the rule. */}
                  {rules.some(
                    (rule) =>
                      rule.id === alert.reorder_rule_id &&
                      !rule.preferred_partner_id,
                  )
                    ? t("reorderRules.alertSupplierPriceList", {
                        supplier: alert.preferred_partner_name,
                      })
                    : t("reorderRules.alertSupplier", {
                        supplier: alert.preferred_partner_name,
                      })}
                </span>
              ) : (
                <Badge variant="warning">{t("reorderRules.noSupplier")}</Badge>
              )}
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  );
}

/**
 * A product the organization makes is produced, not bought: the alert says so
 * and, for an account that may plan runs, opens the production screen on the
 * product with what the shelf is missing.
 */
function MakeInsteadAction({
  alert,
  canWrite,
}: {
  alert: ReplenishmentAlert;
  canWrite: boolean;
}) {
  const { t } = useTranslation("purchase_orders");
  const navigate = useNavigate();
  const quantity = alert.remaining_to_buy ?? alert.suggested_reorder_quantity;
  return (
    <>
      <Badge variant="info">{t("reorderRules.madeHere")}</Badge>
      {canWrite && quantity > 0 && (
        <Button
          size="sm"
          variant="outline"
          leftIcon={<Hammer size={14} />}
          onClick={() =>
            navigate(
              `/maker/production?plan=${alert.product_template_id}` +
                `&quantity=${quantity}`,
            )
          }
        >
          {t("reorderRules.planRun")}
        </Button>
      )}
    </>
  );
}
