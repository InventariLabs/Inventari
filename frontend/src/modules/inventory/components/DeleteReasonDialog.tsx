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
  /** Replaces the single-record title when the dialog asks for a batch. */
  title?: string;
  /** Replaces the single-record body when the dialog asks for a batch. */
  message?: string;
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
  title,
  message,
  onConfirm,
  onCancel,
}: DeleteReasonDialogProps) {
  const { t } = useTranslation(["items", "common"]);
  // No default: "Other" is never pre-selected, since it is the last entry on
  // the list and the only one that means nothing. A quick click must not file
  // the answer that cannot be counted.
  const [reason, setReason] = useState("");
  const [notes, setNotes] = useState("");

  return (
    <ConfirmDialog
      open={open}
      title={title ?? t("items:actions.confirmDelete")}
      message={message ?? t("items:messages.deleteGoesToArchive")}
      confirmLabel={t("items:actions.delete")}
      cancelLabel={t("common:actions.cancel")}
      variant="danger"
      confirmDisabled={reason === ""}
      onConfirm={() => onConfirm(reason, notes)}
      errorFallback={t("items:messages.deleteFailed")}
      onCancel={onCancel}
    >
      <div className="space-y-3">
        {itemName && (
          <p className="text-sm text-on-secondary font-medium">{itemName}</p>
        )}
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
