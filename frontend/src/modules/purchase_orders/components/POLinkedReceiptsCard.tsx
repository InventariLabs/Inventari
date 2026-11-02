import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { QueryError } from "@/components/ui/QueryResult";

interface POLinkedReceiptsCardProps {
  poId: string;
  /** Number of linked receipt documents, regardless of their status. */
  receiptCount: number;
  isLoading?: boolean;
  /** The read failed: the count is unknown, not zero. */
  isError?: boolean;
  onRetry?: () => void;
}

export function POLinkedReceiptsCard({
  poId,
  receiptCount,
  isLoading = false,
  isError = false,
  onRetry,
}: POLinkedReceiptsCardProps) {
  const { t } = useTranslation(["purchase_orders", "common"]);
  const navigate = useNavigate();

  return (
    <Card className="p-5">
      <h2 className="text-sm font-medium text-on-secondary mb-3">
        {t("linkedReceipts")}
      </h2>
      {isLoading ? (
        <div className="text-sm text-on-secondary">
          {t("common:messages.loading")}
        </div>
      ) : isError ? (
        <QueryError onRetry={onRetry} />
      ) : receiptCount > 0 ? (
        <div className="space-y-2">
          <div className="text-xs text-on-secondary">{t("receiptsNote")}</div>
          <Button
            variant="secondary"
            size="sm"
            onClick={() => navigate(`/purchase-orders/${poId}/linked-receipts`)}
          >
            {t("viewLinkedReceipts")}
          </Button>
        </div>
      ) : (
        <div className="text-sm text-on-secondary">{t("noReceiptsYet")}</div>
      )}
    </Card>
  );
}
