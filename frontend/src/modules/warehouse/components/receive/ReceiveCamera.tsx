import { useState } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { ScanCameraPanel } from "@/components/ui/ScanCameraPanel";
import { useScanCamera } from "@/hooks/useScanCamera";
import { extractApiError } from "@/lib/errors";
import { documentsProductsApi } from "@/modules/warehouse/api/documents_products";
import type { ProductSearchResult } from "@/modules/warehouse/api/documents";

interface Props {
  onSelect: (product: ProductSearchResult) => void;
  onClose: () => void;
}

/**
 * The camera of the phone's receive screen. The camera hook runs it while
 * the reader is on the page, so mounting this opens it and unmounting stops it.
 *
 * A code it reads is looked up the way a scanner's Enter in the scan field
 * is, and lands on the same callback. Its own chunk: the decoder is the
 * heaviest thing on the screen, and a phone pays for it only once the
 * worker asks for the camera.
 */
export default function ReceiveCamera({ onSelect, onClose }: Props) {
  const { t } = useTranslation("warehouse");
  const [missed, setMissed] = useState<string | null>(null);
  const camera = useScanCamera({
    onCodeScanned: (code) => {
      documentsProductsApi.productSearch(code, 5).then(
        (found) => {
          setMissed(found.length > 0 ? null : code);
          if (found.length > 0) onSelect(found[0]);
        },
        (error: unknown) =>
          toast.error(extractApiError(error, t("scan.error"))),
      );
    },
  });
  return (
    <>
      <ScanCameraPanel
        open
        pinned
        scannerError={camera.scannerError}
        isCameraActive={camera.isCameraActive}
        isTorchOn={camera.isTorchOn}
        onRetry={camera.restartCamera}
        onToggleTorch={camera.toggleTorch}
        onClose={onClose}
      />
      {missed && (
        <p role="alert" className="text-sm text-on-warning">
          {t("receive.noProductFound", { code: missed })}
        </p>
      )}
    </>
  );
}
