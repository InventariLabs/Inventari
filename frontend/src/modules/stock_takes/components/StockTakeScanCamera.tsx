import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Camera, CameraOff } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { ScanCameraPanel } from "@/components/ui/ScanCameraPanel";
import { useScanCamera } from "@/hooks/useScanCamera";

/**
 * The phone's camera as the counting screen's scanner. Closed until asked
 * for: the cards are the work here, and a picture over them on every visit
 * would push them below the fold. What it reads takes the same path as a
 * code typed or read by a hardware scanner.
 */
export default function StockTakeScanCamera({
  onCode,
}: {
  onCode: (code: string) => void;
}) {
  const { t } = useTranslation(["stock_takes", "scan"]);
  const [open, setOpen] = useState(false);
  const {
    scannerError,
    isCameraActive,
    setIsCameraActive,
    restartCamera,
    isTorchOn,
    toggleTorch,
  } = useScanCamera({ onCodeScanned: onCode });

  const close = () => {
    setIsCameraActive(false);
    setOpen(false);
  };

  const toggle = () => {
    if (open) setIsCameraActive(false);
    else restartCamera();
    setOpen(!open);
  };

  return (
    <div className="mt-2 space-y-2">
      <Button
        size="sm"
        variant={open ? "primary" : "outline"}
        onClick={toggle}
        aria-expanded={open}
        leftIcon={open ? <CameraOff size={16} /> : <Camera size={16} />}
      >
        {open ? t("scan.cameraClose") : t("scan.cameraOpen")}
      </Button>
      <ScanCameraPanel
        open={open}
        pinned
        scannerError={scannerError}
        isCameraActive={isCameraActive}
        isTorchOn={isTorchOn}
        onRetry={restartCamera}
        onToggleTorch={toggleTorch}
        onClose={close}
      />
    </div>
  );
}
