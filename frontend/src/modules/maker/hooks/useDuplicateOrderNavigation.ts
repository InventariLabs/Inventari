import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { useDuplicateProductionOrder } from "@/modules/maker/hooks/useProduction";
import { extractApiError } from "@/lib/errors";

/**
 * Shared duplicate-order action used by the production list cards and the
 * order detail page. Duplicates the order, toasts, and navigates to the new
 * order. Pass the originating MouseEvent to stop card-click propagation.
 */
export function useDuplicateOrderNavigation() {
  const { t } = useTranslation("maker");
  const navigate = useNavigate();
  const duplicateMutation = useDuplicateProductionOrder();

  function duplicate(orderId: string, e?: React.MouseEvent) {
    e?.stopPropagation();
    duplicateMutation.mutate(orderId, {
      onSuccess: (newOrder) => {
        toast.success(t("detail.duplicated"));
        navigate(`/maker/production/${newOrder.id}`);
      },
      onError: (err) => {
        toast.error(extractApiError(err, t("detail.duplicateFailed")));
      },
    });
  }

  return { duplicate, isDuplicating: duplicateMutation.isPending };
}
