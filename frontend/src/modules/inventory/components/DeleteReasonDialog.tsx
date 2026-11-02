import { useState } from "react";
import { useTranslation } from "react-i18next";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { Input } from "@/components/ui/Input";
import { NativeSelect } from "@/components/ui/NativeSelect";
import {
  DELETION_REASONS,
  reasonLabelKey,
} from "@/modules/inventory/constants/stockReasons";

interface DeleteReasonDialogProps {
  open: boolean;
  itemName: string;
  /**
   * Returning a promise keeps the dialog open until the delete settles, and
   * keeps the reason and note as typed when it fails — see ConfirmDialog.
   */
  onConfirm: (reason: string, notes: string) => unknown;
  onCancel: () => void;
}

export function DeleteReasonDialog({
  open,
  itemName,
  onConfirm,
  onCancel,
}: DeleteReasonDialogProps) {
  const { t } = useTranslation(["items", "common"]);
  // No default. "Other" used to be pre-selected — the last entry on the list
  // and the only one that means nothing — so whoever clicked quickly filed
  // the answer that cannot be counted, and the archive filled up with it.
  const [reason, setReason] = useState("");
  const [notes, setNotes] = useState("");

  return (
    <ConfirmDialog
      open={open}
      title={t("items:actions.confirmDelete")}
      message={t("items:messages.deleteGoesToArchive")}
      confirmLabel={t("items:actions.delete")}
      cancelLabel={t("common:actions.cancel")}
      variant="danger"
      confirmDisabled={reason === ""}
      onConfirm={() => onConfirm(reason, notes)}
      errorFallback={t("items:messages.deleteFailed")}
      onCancel={onCancel}
    >
      <div className="space-y-3">
        <p className="text-sm text-on-secondary font-medium">{itemName}</p>
        <div>
          <NativeSelect
            label={t("items:deletionReason")}
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            data-testid="deletion-reason"
          >
            <option value="" disabled>
              {t("items:deletionReasonPlaceholder")}
            </option>
            {DELETION_REASONS.map((value) => (
              <option key={value} value={value}>
                {t(reasonLabelKey(value))}
              </option>
            ))}
          </NativeSelect>
        </div>
        <div>
          <Input
            label={t("items:deletionNotes")}
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            placeholder={t("items:deletionNotesPlaceholder")}
          />
        </div>
      </div>
    </ConfirmDialog>
  );
}
