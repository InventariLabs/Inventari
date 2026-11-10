import { useTranslation } from "react-i18next";
import { QrCode } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { SendToPrinterButton } from "@/modules/shared/components/SendToPrinterButton";
import type { StorageLocation } from "@/types";

/**
 * A location's label in its page header: the file to download, and — once a
 * print agent has registered — the same label sent straight to the printer.
 * A location without a short code has no label to send.
 */
export function StorageLabelActions({
  storage,
  onDownload,
}: {
  storage: StorageLocation;
  onDownload: () => void;
}) {
  const { t } = useTranslation("labels");
  return (
    <>
      <Button
        variant="secondary"
        onClick={onDownload}
        aria-label={t("actions.downloadOne")}
        leftIcon={<QrCode size={16} />}
      >
        <span className="hidden sm:inline">{t("actions.downloadOne")}</span>
      </Button>
      {storage.short_code && (
        <SendToPrinterButton
          target={{ storageIds: [storage.id] }}
          variant="secondary"
          textClassName="hidden sm:inline"
        />
      )}
    </>
  );
}
