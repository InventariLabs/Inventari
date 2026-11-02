import { memo } from "react";
import { useTranslation } from "react-i18next";
import {
  FileText,
  CheckCircle,
  XCircle,
  PencilLine,
  Building2,
} from "lucide-react";
import { ActionMenu, type ActionMenuAction } from "@/components/ui/ActionMenu";
import { Button } from "@/components/ui/Button";
import { Badge } from "@/components/ui/Badge";
import { useMediaQuery } from "@/hooks/useMediaQuery";
import {
  formatDate,
  formatMoney,
  formatQuantityValue,
  toAmount,
} from "@/utils/formatters";
import { unitLabel } from "@/lib/i18nHelpers";
import type { PurchaseOrderRow } from "@/modules/purchase_orders/types/purchase-orders";
import { STATUS_COLORS } from "@/modules/purchase_orders/lib/statusColors";

interface Props {
  purchaseOrder: PurchaseOrderRow;
  /** Whether this account may change the order — the row's actions are writes. */
  canWrite: boolean;
  /** Cancelling answers to `purchase_orders:manage`, a step above writing. */
  canManage: boolean;
  onView: () => void;
  onEdit: () => void;
  onConfirm: () => void;
  onCancel: () => void;
}

const PurchaseOrderListItem = memo(function PurchaseOrderListItem({
  purchaseOrder,
  canWrite,
  canManage,
  onView,
  onEdit,
  onConfirm,
  onCancel,
}: Props) {
  const { t, i18n } = useTranslation("purchase_orders");
  const po = purchaseOrder;
  const lang = i18n.language?.substring(0, 2) ?? "en";
  const hasAmount = (toAmount(po.total_gross) ?? 0) > 0;
  const receipt = buildReceiptProgress(po);

  return (
    <div
      data-testid="purchase-order-card"
      className="bg-surface-card rounded-lg border border-border p-4"
    >
      <div className="flex items-start justify-between gap-4">
        {" "}
        <Button
          size="content"
          type="button"
          variant="ghost"
          onClick={onView}
          className="flex-1 justify-start items-start gap-3 text-left min-h-11 md:min-h-0 min-w-11 md:min-w-0"
        >
          <FileText className="w-5 h-5 text-on-secondary mt-0.5 shrink-0" />
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <span className="font-medium text-on dark:text-white">
                {po.number}
              </span>
              <Badge variant={STATUS_COLORS[po.status] ?? "default"}>
                {t(`status.${po.status}`)}
              </Badge>
              {hasAmount && (
                <span className="font-semibold text-on tabular-nums">
                  {formatMoney(po.total_gross, po.currency, lang)}
                </span>
              )}
              {po.total_gross === null && (
                <span className="text-sm text-on-muted">{t("noPriceYet")}</span>
              )}
            </div>
            <div className="text-sm text-on-secondary dark:text-on-muted mt-1">
              {t("lines", { count: po.line_count })}
              {po.partner_name && (
                <span className="ml-2 inline-flex items-center gap-1">
                  <Building2 size={13} className="inline text-on-muted" />
                  {po.partner_name}
                </span>
              )}
              {po.scheduled_date && (
                <span className="ml-2">
                  {t("scheduled")}: {formatDate(po.scheduled_date)}
                  {isOverdue(po) && <OverdueBadge po={po} />}
                </span>
              )}
              {/* how much of a confirmed order has arrived. The row
                  said what was ordered and never what was received, which is
                  the question the list is usually opened with. */}
              {receipt && <ReceiptProgress groups={receipt} legend />}
            </div>
          </div>
        </Button>
        <RowActions
          status={po.status}
          canWrite={canWrite}
          canManage={canManage}
          onEdit={onEdit}
          onConfirm={onConfirm}
          onCancel={onCancel}
        />
      </div>
    </div>
  );
});

/**
 * A confirmed order whose scheduled date has passed. Only a confirmed order
 * is waiting on a delivery; a draft's date is a plan, not a promise.
 */
export function isOverdue(po: PurchaseOrderRow, now = new Date()): boolean {
  if (po.status !== "CONFIRMED" || !po.scheduled_date) return false;
  const today = [
    now.getFullYear(),
    String(now.getMonth() + 1).padStart(2, "0"),
    String(now.getDate()).padStart(2, "0"),
  ].join("-");
  return po.scheduled_date.slice(0, 10) < today;
}

export function OverdueBadge({ po }: { po: PurchaseOrderRow }) {
  const { t } = useTranslation("purchase_orders");
  return (
    <Badge
      variant="danger"
      className="ml-1.5"
      title={t("overdueHint", { date: formatDate(po.scheduled_date) })}
    >
      {t("overdue")}
    </Badge>
  );
}

/** Units received against units ordered, while an order is being fulfilled. */
interface ReceiptUnitProgress {
  unit: string | null;
  received: number;
  ordered: number;
}

/**
 * One figure per unit the order is measured in.
 *
 * The row summed every line into a single pair and a single bar, so an
 * order of 20 pcs + 12.5 kg + 30 pack reported "56.5/62.5" — a progression
 * in no unit at all. Quantities may be added up only when they share a
 * measure; the detail page has always shown each line in its own unit.
 */
export function buildReceiptProgress(
  po: PurchaseOrderRow,
): ReceiptUnitProgress[] | null {
  if (po.status !== "CONFIRMED" || po.line_count === 0) return null;
  // Summed per unit by the server, in the order the lines first name them.
  const groups = po.unit_progress.map((group) => ({
    unit: group.unit,
    received: Number(group.received),
    ordered: Number(group.ordered),
  }));
  const ordered = groups.reduce((sum, group) => sum + group.ordered, 0);
  if (ordered <= 0) return null;
  return groups;
}

/**
 * A single-unit order keeps its bar and its pair; an order of several units
 * gets one pair per unit and no bar, because a bar needs one denominator.
 * A line that carries no unit is a group of its own — "units" is what the
 * rest of the module calls it.
 */
export function ReceiptProgress({
  groups,
  legend = false,
}: {
  groups: ReceiptUnitProgress[];
  /** Name the counter in words — a card has no column header to do it. */
  legend?: boolean;
}) {
  const { t } = useTranslation("purchase_orders");

  if (groups.length > 1) {
    const progress = groups
      .map(
        (group) =>
          `${formatQuantityValue(group.received)}/${formatQuantityValue(
            group.ordered,
          )} ${unitLabel(t, group.unit) || t("units")}`,
      )
      .join(" · ");
    return (
      <span
        className="ml-2 text-xs tabular-nums"
        title={t("receivedProgressPerUnit", { progress })}
      >
        {legend ? t("receivedProgressPerUnit", { progress }) : progress}
      </span>
    );
  }

  const single = groups[0];
  if (!single) return null;
  const label = t("receivedProgress", {
    received: formatQuantityValue(single.received),
    ordered: formatQuantityValue(single.ordered),
  });
  return (
    <span
      className="ml-2 inline-flex items-center gap-1.5 align-middle"
      title={label}
    >
      <span
        role="meter"
        aria-valuemin={0}
        aria-valuemax={single.ordered}
        aria-valuenow={single.received}
        aria-label={label}
        className="h-1 w-10 rounded-full bg-surface-inset overflow-hidden inline-block"
      >
        <span
          className="block h-full bg-accent-500"
          style={{
            width: `${Math.min(100, Math.round((single.received / single.ordered) * 100))}%`,
          }}
        />
      </span>
      <span className="text-xs tabular-nums">
        {legend
          ? label
          : `${formatQuantityValue(single.received)}/${formatQuantityValue(
              single.ordered,
            )} ${unitLabel(t, single.unit) || t("units")}`}
      </span>
    </span>
  );
}

interface RowActionsProps {
  status: PurchaseOrderRow["status"];
  canWrite: boolean;
  canManage: boolean;
  onEdit: () => void;
  onConfirm: () => void;
  onCancel: () => void;
}

/**
 * Edit and Confirm stay on the row from sm up; cancelling is destructive and
 * rare, so it lives in the "⋯" menu instead of reading as a red link on every
 * row. On a phone three labelled buttons overflow the card (the page has no
 * horizontal scroll), so there the menu holds all of them. Actions render
 * exactly once per viewport size (useMediaQuery), which keeps the sm+ markup
 * testable in JSDOM.
 *
 * Everything in here writes — Edit, Confirm, Cancel all reach the API —
 * so a reader without the permission gets the row without them. Cancel asks
 * for more than writing: the endpoint answers to `purchase_orders:manage`, so
 * an account that only writes is not offered a button that ends in a 403.
 */
export function RowActions({
  status,
  canWrite,
  canManage,
  onEdit,
  onConfirm,
  onCancel,
}: RowActionsProps) {
  const { t } = useTranslation("purchase_orders");
  const isMobile = useMediaQuery("(max-width: 639px)");

  if (!canWrite) {
    return null;
  }

  const isDraft = status === "DRAFT";
  const canCancel =
    canManage &&
    (isDraft || status === "CONFIRMED" || status === "PENDING_APPROVAL");
  const edit: ActionMenuAction = {
    id: "edit",
    label: t("edit"),
    icon: <PencilLine className="w-4 h-4" />,
    onSelect: onEdit,
  };
  const confirm: ActionMenuAction = {
    id: "confirm",
    label: t("confirm"),
    icon: <CheckCircle className="w-4 h-4" />,
    onSelect: onConfirm,
  };
  const cancel: ActionMenuAction = {
    id: "cancel",
    label: t("cancelOrderAction"),
    icon: <XCircle className="w-4 h-4" />,
    onSelect: onCancel,
    destructive: true,
  };
  const menu = [
    ...(isMobile && isDraft ? [edit, confirm] : []),
    ...(canCancel ? [cancel] : []),
  ];

  return (
    <div className="flex items-center gap-2 shrink-0">
      {!isMobile && isDraft && (
        <>
          <Button variant="ghost" size="sm" onClick={onEdit}>
            {t("edit")}
          </Button>
          <Button variant="secondary" size="sm" onClick={onConfirm}>
            <CheckCircle className="w-4 h-4 mr-1" />
            {t("confirm")}
          </Button>
        </>
      )}
      {menu.length > 0 && (
        <ActionMenu actions={menu} label={t("moreActions")} />
      )}
    </div>
  );
}

export default PurchaseOrderListItem;
