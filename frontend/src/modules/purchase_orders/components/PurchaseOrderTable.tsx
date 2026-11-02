import { useTranslation } from "react-i18next";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { cn } from "@/lib/utils";
import { formatDate, formatMoney, toAmount } from "@/utils/formatters";
import type { PurchaseOrderRow } from "@/modules/purchase_orders/types/purchase-orders";
import { STATUS_COLORS } from "@/modules/purchase_orders/lib/statusColors";
import {
  OverdueBadge,
  ReceiptProgress,
  RowActions,
  buildReceiptProgress,
  isOverdue,
} from "./PurchaseOrderListItem";

interface Props {
  purchaseOrders: PurchaseOrderRow[];
  canWrite: boolean;
  canManage: boolean;
  onView: (po: PurchaseOrderRow) => void;
  onEdit: (po: PurchaseOrderRow) => void;
  onConfirm: (po: PurchaseOrderRow) => void;
  onCancel: (po: PurchaseOrderRow) => void;
}

/**
 * The desktop list of purchase orders: a `<table>` (§14.1), so the received
 * counter sits under a header that says what it counts and the scheduled date
 * sits where an overdue flag can follow it. The phone keeps the card.
 */
export function PurchaseOrderTable({
  purchaseOrders,
  canWrite,
  canManage,
  onView,
  onEdit,
  onConfirm,
  onCancel,
}: Props) {
  const { t, i18n } = useTranslation("purchase_orders");
  const lang = i18n.language?.substring(0, 2) ?? "en";
  const heading = "px-3 py-2.5 font-medium text-on-secondary";
  return (
    <div className="relative overflow-x-auto rounded-lg border border-border bg-surface-card">
      <table className="w-full text-sm min-w-[860px]">
        <thead>
          <tr className="border-b border-border text-left text-xs uppercase tracking-wide">
            <th scope="col" className={heading}>
              {t("columns.number")}
            </th>
            <th scope="col" className={heading}>
              {t("columns.status")}
            </th>
            <th scope="col" className={heading}>
              {t("columns.supplier")}
            </th>
            <th scope="col" className={cn(heading, "text-right")}>
              {t("columns.lines")}
            </th>
            <th scope="col" className={heading}>
              {t("columns.scheduled")}
            </th>
            <th scope="col" className={heading}>
              {t("columns.received")}
            </th>
            <th scope="col" className={cn(heading, "text-right")}>
              {t("columns.total")}
            </th>
            {canWrite && (
              <th scope="col" className={heading}>
                <span className="sr-only">{t("columns.actions")}</span>
              </th>
            )}
          </tr>
        </thead>
        <tbody>
          {purchaseOrders.map((po) => {
            const receipt = buildReceiptProgress(po);
            return (
              <tr
                key={po.id}
                className="border-b border-border last:border-b-0 hover:bg-surface-raised"
              >
                <td className="px-3 py-2.5">
                  <Button
                    size="content"
                    type="button"
                    variant="ghost"
                    onClick={() => onView(po)}
                    className="py-2 min-h-11 md:min-h-10 font-medium text-on"
                  >
                    {po.number}
                  </Button>
                </td>
                <td className="px-3 py-2.5">
                  <Badge variant={STATUS_COLORS[po.status] ?? "default"}>
                    {t(`status.${po.status}`)}
                  </Badge>
                </td>
                <td className="px-3 py-2.5 text-on-secondary">
                  {po.partner_name ?? "—"}
                </td>
                <td className="px-3 py-2.5 text-right tabular-nums">
                  {t("lines", { count: po.line_count })}
                </td>
                <td className="px-3 py-2.5 text-on-secondary">
                  {po.scheduled_date ? (
                    <>
                      {formatDate(po.scheduled_date)}
                      {isOverdue(po) && <OverdueBadge po={po} />}
                    </>
                  ) : (
                    "—"
                  )}
                </td>
                <td className="px-3 py-2.5 text-on-secondary">
                  {receipt ? <ReceiptProgress groups={receipt} /> : "—"}
                </td>
                <td className="px-3 py-2.5 text-right font-semibold tabular-nums">
                  {po.total_gross === null ? (
                    <span className="font-normal text-on-muted">
                      {t("noPriceYet")}
                    </span>
                  ) : (toAmount(po.total_gross) ?? 0) > 0 ? (
                    formatMoney(po.total_gross, po.currency, lang)
                  ) : (
                    "—"
                  )}
                </td>
                {canWrite && (
                  <td className="px-3 py-2.5">
                    <RowActions
                      status={po.status}
                      canWrite={canWrite}
                      canManage={canManage}
                      onEdit={() => onEdit(po)}
                      onConfirm={() => onConfirm(po)}
                      onCancel={() => onCancel(po)}
                    />
                  </td>
                )}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
