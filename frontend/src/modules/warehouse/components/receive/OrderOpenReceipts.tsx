import { documentTitle } from "@/modules/warehouse/lib/documentTitle";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/Button";
import { InlineQueryError } from "@/components/ui/QueryResult";
import { useOrderOpenReceipts } from "@/hooks/useOpenPurchaseOrders";

/**
 * The order's receipts that already hold part of what it still owes.
 *
 * A receipt drafted or confirmed for the order, and not yet posted, speaks
 * for its goods: a delivery received beside it on this screen is weighed
 * with that part spoken for, so the post meets a refusal nothing on the
 * sheet explains. The screen names each such receipt and offers to receive
 * through it — a confirmed one opens on its receiving session, a draft on
 * its own page.
 */
export function OrderOpenReceipts({
  order,
}: {
  order: { id: string; number: string } | null;
}) {
  const { t } = useTranslation("warehouse");
  const navigate = useNavigate();
  const { receipts, error, isError, refetch } = useOrderOpenReceipts(
    order?.id ?? null,
  );
  if (!order) return null;
  if (isError) {
    return (
      <InlineQueryError
        error={error}
        message={t("receive.openReceipts.loadFailed")}
        onRetry={() => void refetch()}
      />
    );
  }
  if (receipts.length === 0) return null;

  return (
    <div
      role="status"
      className="space-y-2 rounded-lg bg-amber-50 px-4 py-3 text-sm text-on-warning"
    >
      <p>
        {t("receive.openReceipts.notice", {
          number: order.number,
          count: receipts.length,
        })}
      </p>
      <div className="flex flex-wrap gap-2">
        {receipts.map((receipt) => (
          <Button
            key={receipt.id}
            variant="outline"
            size="sm"
            onClick={() =>
              navigate(
                receipt.status === "CONFIRMED"
                  ? `/warehouse/documents/${receipt.id}#receive`
                  : `/warehouse/documents/${receipt.id}`,
              )
            }
          >
            {t("receive.openReceipts.receiveThrough", {
              number: documentTitle(t, receipt),
            })}
          </Button>
        ))}
      </div>
    </div>
  );
}
