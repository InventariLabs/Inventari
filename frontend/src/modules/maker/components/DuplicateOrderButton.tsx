import { useTranslation } from "react-i18next";
import { Copy } from "lucide-react";

import { Button } from "@/components/ui/Button";

interface Props {
  orderId: string;
  isDuplicating: boolean;
  onDuplicate: (orderId: string, event: React.MouseEvent) => void;
  /** `maker-card-…` on a card, `maker-row-…` in the table. */
  testId: string;
}

/**
 * "Duplicate this order" — the same button on the card and in the row.
 *
 * Written out twice, it was also gated twice, which is how one of the two
 * ends up keeping the offer for an account that may not take it.
 */
export function DuplicateOrderButton({
  orderId,
  isDuplicating,
  onDuplicate,
  testId,
}: Props) {
  const { t } = useTranslation("maker");

  return (
    <Button
      size="sm"
      variant="ghost"
      onClick={(e) => onDuplicate(orderId, e)}
      disabled={isDuplicating}
      leftIcon={<Copy size={14} />}
      data-testid={testId}
    >
      {t("productionList.duplicate")}
    </Button>
  );
}
