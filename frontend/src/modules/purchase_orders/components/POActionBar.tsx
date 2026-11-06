import { useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import * as PopoverPrimitive from "@radix-ui/react-popover";
import {
  CheckCircle,
  XCircle,
  Mail,
  Download,
  ListChecks,
  MoreHorizontal,
  PackagePlus,
  PencilLine,
} from "lucide-react";
import { ActionMenu } from "@/components/ui/ActionMenu";
import { Button } from "@/components/ui/Button";
import { useMediaQuery } from "@/hooks/useMediaQuery";
import type { PurchaseOrder } from "../types/purchase-orders";
import type { POActionType } from "./POActionDialogs";

interface POActionBarProps {
  po: PurchaseOrder;
  canManage: boolean;
  /**
   * Whether the account may decide on a pending approval. The endpoint
   * checks `approvals:approve`, not `purchase_orders:manage`: a manager who
   * is not an approver saw Approve/Reject and learned the rule from a 403,
   * while an approver without manage never saw them at all.
   */
  canDecide: boolean;
  /** False leaves only the reads — the PDF. */
  canWrite: boolean;
  approvalsEnabled: boolean;
  /**
   * Whether the engine would accept a request for this order — an active
   * ``purchase_order`` workflow with a stage, the server's own test. ``false``
   * hides the request action, because the endpoint behind it would only
   * refuse; ``undefined`` (still unanswered, a failed read) keeps it, so the
   * API stays the last word.
   */
  workflowConfigured?: boolean | undefined;
  /** Whether an approval request is still waiting for a decision. */
  hasPendingApproval: boolean;
  /**
   * Whether the page shows the approval card. The card holds the decision —
   * Approve, Reject, or asking again after a withdrawal — beside the stage it
   * decides, so the header does not offer the same buttons a second time.
   */
  approvalCardShown?: boolean;
  /**
   * Whether the viewer may decide on the pending request, from its
   * ``viewer_can_decide``. ``null``/``undefined`` means the server
   * named no viewer — the permission grant alone then decides, as it always
   * did, so it must not hide the buttons.
   */
  viewer_can_decide?: boolean | null;
  pdfPending: boolean;
  onEdit: () => void;
  onAction: (action: POActionType) => void;
  onDownloadPdf: () => void;
  /** Open the receive screen on this order. */
  onReceive: () => void;
}

type ButtonVariant = "primary" | "secondary" | "ghost" | "danger" | "outline";

interface POActionItem {
  key: string;
  label: string;
  icon: typeof PencilLine;
  variant: ButtonVariant;
  disabled?: boolean;
  /** Why the action is unavailable — a disabled button must say so. */
  disabledReason?: string;
  /**
   * Destructive and rare: kept off the header row, in the "⋯" menu, so it
   * does not read as one more button beside the order's everyday actions.
   */
  destructive?: boolean;
  /**
   * The order's main next step: on a phone it stays on the header row beside
   * the "⋯" instead of inside the menu, while it can run. A disabled one
   * stays in the menu, where its reason is printed under the label.
   */
  promoted?: boolean;
  onClick: () => void;
}

/**
 * The actions a pending order offers: deciding on its request, or asking
 * again when one was withdrawn.
 *
 * Deciding needs something to decide on. When the requester withdraws their
 * own request the order stays parked with nothing pending, and Approve/Reject
 * answered 409 while Request approval demanded DRAFT — three offered actions,
 * no way out. Asking again is the way forward; cancelling, in the bar, is the
 * way back.
 *
 * The grant is only half the answer: a requester who may approve still gets
 * `viewer_can_decide: false` for their own request from the server. The slot
 * already respects it; the header does too, so it never offers a decision
 * that would come back 409. The endpoint checks `approvals:approve` to decide
 * and the order's own write pair to act.
 */
function pendingApprovalItems({
  po,
  canWrite,
  canManage,
  canDecide,
  canRequestApproval,
  hasPendingApproval,
  viewerCanDecide,
  approvalCardShown,
  t,
  onAction,
}: {
  po: PurchaseOrder;
  canWrite: boolean;
  canManage: boolean;
  canDecide: boolean;
  canRequestApproval: boolean;
  hasPendingApproval: boolean;
  viewerCanDecide: boolean;
  approvalCardShown: boolean;
  t: ReturnType<typeof useTranslation>["t"];
  onAction: (action: POActionType) => void;
}): POActionItem[] {
  if (!canWrite || po.status !== "PENDING_APPROVAL") return [];
  // The card on the page answers every state of the request — open,
  // withdrawn, rejected — with the same gates; two copies of Approve read as
  // two different decisions.
  if (approvalCardShown) return [];
  if (hasPendingApproval && canDecide && viewerCanDecide) {
    return [
      {
        key: "approve",
        label: t("approve"),
        icon: CheckCircle,
        variant: "primary",
        onClick: () => onAction("approve"),
      },
      {
        key: "reject",
        label: t("reject"),
        icon: XCircle,
        variant: "danger",
        onClick: () => onAction("reject"),
      },
    ];
  }
  if (!hasPendingApproval && canManage && canRequestApproval) {
    return [
      {
        key: "requestApproval",
        label: t("requestApproval"),
        icon: ListChecks,
        variant: "primary",
        onClick: () => onAction("requestApproval"),
      },
    ];
  }
  return [];
}

/**
 * The order's actions, for the page header.
 *
 * They used to fill a row of their own under the title, with "Scheduled: …"
 * at its other end; the document detail keeps its actions in the header, on
 * the line of the number, and the scheduled date is a field of the details
 * grid.
 */
export function POActionBar({
  po,
  canManage,
  canDecide,
  canWrite,
  approvalsEnabled,
  workflowConfigured,
  hasPendingApproval,
  approvalCardShown = false,
  viewer_can_decide,
  pdfPending,
  onEdit,
  onAction,
  onDownloadPdf,
  onReceive,
}: POActionBarProps) {
  const { t } = useTranslation(["purchase_orders", "common"]);
  // The slot gates Approve/Reject on `viewer_can_decide`; the header must too,
  // so a requester who is also a manager never sees a decision that the server
  // will answer with 409. ``null`` (no viewer named) keeps the old
  // grant-only behaviour.
  const viewerCanDecide = viewer_can_decide !== false;
  // Asking is offered only where the engine would take the request: no
  // workflow, and the proxy endpoint answers 409 after the click. The
  // workflow list cannot answer this for the account composing the request
  // (it is filtered by `approvals:read`), so the bit comes from its own
  // endpoint. An unanswered question keeps the old offer.
  const canRequestApproval = approvalsEnabled && workflowConfigured !== false;

  const items: POActionItem[] = [];
  if (canWrite && po.status === "DRAFT") {
    items.push({
      key: "edit",
      label: t("edit"),
      icon: PencilLine,
      variant: "secondary",
      onClick: onEdit,
    });
    items.push({
      key: "confirm",
      label: t("confirm"),
      icon: CheckCircle,
      variant: "primary",
      // A draft's next step: on a phone it stays beside the "⋯".
      promoted: true,
      onClick: () => onAction("confirm"),
    });
    if (canRequestApproval) {
      items.push({
        key: "requestApproval",
        label: t("requestApproval"),
        icon: ListChecks,
        variant: "ghost",
        onClick: () => onAction("requestApproval"),
      });
    }
  }
  items.push(
    ...pendingApprovalItems({
      po,
      canWrite,
      canManage,
      canDecide,
      canRequestApproval,
      hasPendingApproval,
      viewerCanDecide,
      approvalCardShown,
      t,
      onAction,
    }),
  );
  if (po.status === "CONFIRMED" || po.status === "COMPLETED") {
    items.push({
      key: "downloadPdf",
      label: t("downloadPdf"),
      icon: Download,
      variant: "ghost",
      disabled: pdfPending,
      onClick: onDownloadPdf,
    });
  }
  if (canWrite && po.status === "CONFIRMED") {
    // The goods are taken in on the receive screen, which loads the order's
    // open lines and posts them in one press. The icon is a parcel, not the
    // arrow-to-tray the PDF download beside it wears.
    items.push({
      key: "receiveDelivery",
      label: t("receiveDelivery"),
      icon: PackagePlus,
      variant: "secondary",
      promoted: true,
      // The receive screen finds the order through its supplier.
      disabled: !po.partner_id,
      disabledReason: t("receiveDeliveryNoPartner"),
      onClick: onReceive,
    });
  }
  if (canWrite && (po.status === "CONFIRMED" || po.status === "COMPLETED")) {
    items.push({
      key: "send",
      label: t("sendToVendor"),
      icon: Mail,
      variant: "ghost",
      // Confirming needs a supplier now, but orders confirmed before
      // that rule still exist — and "send to the supplier" on an order with
      // no supplier can only end in a refusal.
      disabled: !po.partner_id,
      disabledReason: t("sendToVendorNoPartner"),
      onClick: () => onAction("send"),
    });
  }

  if (
    canWrite &&
    canManage &&
    (po.status === "DRAFT" ||
      po.status === "CONFIRMED" ||
      po.status === "PENDING_APPROVAL")
  ) {
    items.push({
      key: "cancel",
      label: t("cancelOrderAction"),
      icon: XCircle,
      variant: "ghost",
      destructive: true,
      onClick: () => onAction("cancel"),
    });
  }
  return (
    <Actions
      items={items}
      moreLabel={t("moreActions", { ns: "purchase_orders" })}
    />
  );
}

/**
 * A disabled button takes no pointer events, so its `title` never shows; the
 * reason rides on a wrapper that does.
 */
function ReasonWrap({
  item,
  className,
  children,
}: {
  item: POActionItem;
  className?: string;
  children: ReactNode;
}) {
  return (
    <span
      className={className}
      title={item.disabled ? item.disabledReason : undefined}
    >
      {children}
    </span>
  );
}

/**
 * Inline buttons on sm+; a "⋯" overflow menu on phones — the same
 * pattern as RowActions in PurchaseOrderListItem. On a 390 px
 * viewport four labelled buttons overflow the page ("Cancel" ended at
 * x = 464 px) and the page has no horizontal scroll. Actions render exactly
 * once per viewport size (useMediaQuery), which keeps the sm+ markup
 * testable in JSDOM.
 */
function Actions({
  items,
  moreLabel,
}: {
  items: POActionItem[];
  moreLabel: string;
}) {
  const isMobile = useMediaQuery("(max-width: 639px)");
  const [open, setOpen] = useState(false);

  if (items.length === 0) {
    return null;
  }

  if (!isMobile) {
    const menu = items.filter((item) => item.destructive);
    return (
      <div className="flex items-center gap-2 shrink-0">
        {items
          .filter((item) => !item.destructive)
          .map((item) => (
            <ReasonWrap key={item.key} item={item}>
              <Button
                variant={item.variant}
                size="sm"
                onClick={item.onClick}
                disabled={item.disabled}
              >
                <item.icon className="w-4 h-4 mr-1" />
                {item.label}
              </Button>
            </ReasonWrap>
          ))}
        {menu.length > 0 && (
          <ActionMenu
            label={moreLabel}
            actions={menu.map((item) => ({
              id: item.key,
              label: item.label,
              icon: <item.icon className="w-4 h-4" />,
              onSelect: item.onClick,
              destructive: true,
            }))}
          />
        )}
      </div>
    );
  }

  const promoted = items.find((item) => item.promoted && !item.disabled);
  const inMenu = items.filter((item) => item !== promoted);

  return (
    <div className="flex items-center gap-1 shrink-0">
      {promoted && (
        <Button variant={promoted.variant} size="sm" onClick={promoted.onClick}>
          <promoted.icon className="w-4 h-4 mr-1" />
          {promoted.label}
        </Button>
      )}
      {inMenu.length > 0 && (
        <PhoneMenu
          items={inMenu}
          moreLabel={moreLabel}
          open={open}
          setOpen={setOpen}
        />
      )}
    </div>
  );
}

function PhoneMenu({
  items,
  moreLabel,
  open,
  setOpen,
}: {
  items: POActionItem[];
  moreLabel: string;
  open: boolean;
  setOpen: (open: boolean) => void;
}) {
  return (
    <PopoverPrimitive.Root open={open} onOpenChange={setOpen}>
      <PopoverPrimitive.Trigger asChild>
        <Button
          variant="ghost"
          size="icon"
          aria-label={moreLabel}
          title={moreLabel}
          className="shrink-0"
        >
          <MoreHorizontal size={18} />
        </Button>
      </PopoverPrimitive.Trigger>
      <PopoverPrimitive.Portal>
        <PopoverPrimitive.Content
          className="z-[var(--z-popover)] w-56 bg-surface-card rounded-xl border border-border shadow-xl p-1 flex flex-col gap-1"
          sideOffset={4}
          collisionPadding={8}
        >
          {items.map((item) => (
            <ReasonWrap key={item.key} item={item} className="flex flex-col">
              <Button
                variant="ghost"
                size="sm"
                className="w-full justify-start gap-2"
                disabled={item.disabled}
                onClick={() => {
                  setOpen(false);
                  item.onClick();
                }}
              >
                <item.icon className="w-4 h-4" />
                {item.label}
              </Button>
              {item.disabled && item.disabledReason && (
                <span className="px-3 pb-1 text-xs text-on-secondary">
                  {item.disabledReason}
                </span>
              )}
            </ReasonWrap>
          ))}
        </PopoverPrimitive.Content>
      </PopoverPrimitive.Portal>
    </PopoverPrimitive.Root>
  );
}
