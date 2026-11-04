import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import { ListChecks } from "lucide-react";
import { Card } from "@/components/ui/Card";
import { TypedSlot } from "@/components/Slot";
import { usePORequestApprovalMessage } from "../hooks/usePOConfirmMessage";
import type { PurchaseOrder } from "../types/purchase-orders";

interface POApprovalStatusCardProps {
  po: PurchaseOrder;
  /** Approve adapter; receives the note typed in the confirm dialog. */
  onApprove: (requestId: string, notes?: string) => Promise<void>;
  onRequest: () => Promise<void>;
  onReject: (requestId: string, notes: string) => Promise<void>;
}

export function POApprovalStatusCard({
  po,
  onApprove,
  onRequest,
  onReject,
}: POApprovalStatusCardProps) {
  const { t } = useTranslation(["purchase_orders", "common"]);
  // The card's Request approval is the only one on a parked order whose
  // request was withdrawn (the header actions give way to the card), so it
  // asks with the same sentence the draft's dialog does — the dead end, if
  // there is one, is said before the click.
  const requestConsequence = usePORequestApprovalMessage(po);

  return (
    <Card className="p-4 sm:p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        {/* The slot sized itself to its row of chips, so its right-aligned
            Approve and Reject ended mid-card. It takes the card's width;
            the queue link keeps the top-right corner. */}
        <TypedSlot
          className="min-w-0 flex-1 basis-full sm:basis-0"
          name="approval_status_badge"
          data={{
            targetType: "purchase_order",
            targetId: po.id,
            // The request goes through this module's own proxy endpoint,
            // which the purchase_orders router answers to
            // purchase_orders:write — name the module so the request
            // button is gated on the right the API checks.
            requestModule: "purchase_orders",
            requestConsequence,
            onApprove,
            onRequest,
            onReject,
          }}
        />
        <Link
          to="/approvals?status=pending"
          className="inline-flex items-center gap-1 text-xs font-medium text-primary-600 hover:text-primary-700 hover:underline"
        >
          <ListChecks size={14} />
          {t("approvalQueueLink")}
        </Link>
      </div>
    </Card>
  );
}
