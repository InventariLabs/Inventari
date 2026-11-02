import { ScanBarcode } from "lucide-react";
import { useTranslation } from "react-i18next";
import { cn } from "@/lib/utils";

/**
 * Says that a USB or Bluetooth barcode scanner can be used on this screen.
 * Render it only where `useScannerInput` is listening.
 */
export function ScannerReadyHint({ className }: { className?: string }) {
  const { t } = useTranslation("common");
  return (
    <p
      className={cn(
        "flex items-center gap-1 text-xs text-on-secondary",
        className,
      )}
    >
      <ScanBarcode size={12} aria-hidden="true" />
      {t("scannerHint")}
    </p>
  );
}
