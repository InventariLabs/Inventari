import { useTranslation } from "react-i18next";
import { XCircle } from "lucide-react";

import { Button } from "@/components/ui/Button";

interface Props {
  canManage: boolean;
  canWrite: boolean;
  onCancel: () => void;
}

/**
 * "Cancel this run" — the three permission states stay in one place.
 *
 * Taking a run back is the manager's call, the same split the documents
 * module draws between executing a document and cancelling it; the page above
 * threads the flags in. The author of a draft who cannot take it back is owed
 * the reason: a button that is simply gone reads as a missing feature, not as
 * a boundary.
 */
export function CancelRunButton({ canManage, canWrite, onCancel }: Props) {
  const { t } = useTranslation("maker");

  if (!canManage && !canWrite) return null;

  if (!canManage) {
    return (
      <span title={t("detail.cancelNeedsManager")}>
        <Button
          variant="outline"
          leftIcon={<XCircle size={16} />}
          disabled
          data-testid="maker-detail-cancel-button"
        >
          {t("detail.cancel", { defaultValue: "Cancel" })}
        </Button>
      </span>
    );
  }

  return (
    <Button
      variant="outline"
      onClick={onCancel}
      leftIcon={<XCircle size={16} />}
      data-testid="maker-detail-cancel-button"
    >
      {t("detail.cancel", { defaultValue: "Cancel" })}
    </Button>
  );
}
