import { useTranslation } from "react-i18next";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";

interface DiscardDraftDialogProps {
  open: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}

/** The generic "discard what you entered?" question — see `useDiscardGuard`. */
export function DiscardDraftDialog({
  open,
  onConfirm,
  onCancel,
}: DiscardDraftDialogProps) {
  const { t } = useTranslation("common");
  return (
    <ConfirmDialog
      open={open}
      title={t("form.discardTitle")}
      message={t("form.discardMessage")}
      variant="danger"
      confirmLabel={t("form.discardConfirm")}
      cancelLabel={t("form.discardCancel")}
      onConfirm={onConfirm}
      onCancel={onCancel}
    />
  );
}
