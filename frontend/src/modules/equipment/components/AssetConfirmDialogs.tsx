import { useTranslation } from "react-i18next";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";

interface AssetConfirmDialogsProps {
  selectedCount: number;
  showBulkRetireConfirm: boolean;
  showBulkArchiveConfirm: boolean;
  showBulkPurgeConfirm: boolean;
  restoreTarget: string | null;
  purgeTarget: string | null;
  // `unknown`, not `void`: each of these returns the promise the dialog awaits
  // before deciding whether to close (see ConfirmDialog's `onConfirm`).
  onBulkRetire: () => unknown;
  onBulkArchive: () => unknown;
  onBulkPurge: () => unknown;
  onRestore: (id: string) => unknown;
  onSinglePurge: (id: string) => unknown;
  onCancelBulkRetire: () => void;
  onCancelBulkArchive: () => void;
  onCancelBulkPurge: () => void;
  onCancelRestore: () => void;
  onCancelPurge: () => void;
  isRestorePending?: boolean;
}

export function AssetConfirmDialogs({
  selectedCount,
  showBulkRetireConfirm,
  showBulkArchiveConfirm,
  showBulkPurgeConfirm,
  restoreTarget,
  purgeTarget,
  onBulkRetire,
  onBulkArchive,
  onBulkPurge,
  onRestore,
  onSinglePurge,
  onCancelBulkRetire,
  onCancelBulkArchive,
  onCancelBulkPurge,
  onCancelRestore,
  onCancelPurge,
}: AssetConfirmDialogsProps) {
  const { t } = useTranslation("equipment");

  return (
    <>
      <ConfirmDialog
        open={showBulkRetireConfirm}
        title={t("list.confirm_bulk_retire", { count: selectedCount })}
        message={t("list.confirm_bulk_retire_msg")}
        confirmLabel={t("actions.bulk_retire")}
        cancelLabel={t("common:actions.cancel", "Cancel")}
        variant="default"
        onConfirm={onBulkRetire}
        onCancel={onCancelBulkRetire}
      />

      <ConfirmDialog
        open={showBulkArchiveConfirm}
        title={t("list.confirm_bulk_archive", { count: selectedCount })}
        message={t("list.confirm_bulk_archive_msg")}
        confirmLabel={t("actions.bulk_archive", "Archive")}
        cancelLabel={t("common:actions.cancel", "Cancel")}
        variant="warning"
        onConfirm={onBulkArchive}
        onCancel={onCancelBulkArchive}
      />

      <ConfirmDialog
        open={showBulkPurgeConfirm}
        title={t("list.confirm_bulk_purge", { count: selectedCount })}
        message={t("list.confirm_bulk_purge_msg")}
        confirmLabel={t("actions.bulk_purge")}
        cancelLabel={t("common:actions.cancel", "Cancel")}
        variant="danger"
        errorFallback={t("list.purge_failed")}
        onConfirm={onBulkPurge}
        onCancel={onCancelBulkPurge}
      />

      <ConfirmDialog
        open={restoreTarget !== null}
        title={t("actions.restore")}
        message={t("detail.confirm_restore_msg")}
        confirmLabel={t("actions.restore")}
        cancelLabel={t("common:actions.cancel", "Cancel")}
        variant="default"
        onConfirm={() => restoreTarget && onRestore(restoreTarget)}
        onCancel={onCancelRestore}
      />

      <ConfirmDialog
        open={purgeTarget !== null}
        title={t("detail.confirm_purge")}
        message={t("detail.confirm_purge_msg")}
        confirmLabel={t("actions.purge")}
        cancelLabel={t("common:actions.cancel", "Cancel")}
        variant="danger"
        errorFallback={t("list.purge_failed")}
        onConfirm={() => purgeTarget && onSinglePurge(purgeTarget)}
        onCancel={onCancelPurge}
      />
    </>
  );
}
