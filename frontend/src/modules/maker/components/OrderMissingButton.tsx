import { useTranslation } from "react-i18next";
import { ShoppingCart } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/Button";
import { useModules } from "@/contexts/ModulesContext";
import { useCanWrite } from "@/hooks/useCanWrite";
import type { TFunction } from "i18next";
import { useOrderMissing } from "@/modules/maker/hooks/usePlanning";
import type {
  NeedsScope,
  OrderMissingResult,
} from "@/modules/maker/types/maker";

/** What ordering did, in one sentence the toast can carry. */
function summary(t: TFunction<"maker">, result: OrderMissingResult): string {
  const orders = result.purchase_orders.length;
  const listed = result.shopping_list_added;
  const toMake = result.to_make.length;
  const parts: string[] = [];
  if (orders > 0) parts.push(t("planning.order.created", { count: orders }));
  if (listed > 0) parts.push(t("planning.order.listed", { count: listed }));
  if (toMake > 0) parts.push(t("planning.order.toMake", { count: toMake }));
  if (result.unplaced.length > 0)
    parts.push(t("planning.order.unplaced", { count: result.unplaced.length }));
  return parts.length > 0 ? parts.join(" · ") : t("planning.order.nothing");
}

/**
 * "Order what is missing" for one run or for a period's runs: a draft
 * purchase order per supplier, from each ingredient's best price. Offered only
 * where purchasing is on and the account may write orders — with either
 * missing the screen keeps what it can do without it.
 */
export function OrderMissingButton({
  scope,
  className,
}: {
  scope: NeedsScope;
  className?: string;
}) {
  const { t } = useTranslation("maker");
  const { isModuleEnabled } = useModules();
  const canOrder = useCanWrite("purchase_orders");
  const order = useOrderMissing(t("planning.order.failed"));
  if (!isModuleEnabled("purchase_orders") || !canOrder) return null;
  return (
    <Button
      size="sm"
      variant="outline"
      className={className}
      leftIcon={<ShoppingCart size={14} />}
      isLoading={order.isPending}
      onClick={() =>
        order.mutate(scope, {
          onSuccess: (result) => toast.success(summary(t, result)),
        })
      }
      data-testid="maker-order-missing"
    >
      {t("planning.order.button")}
    </Button>
  );
}
