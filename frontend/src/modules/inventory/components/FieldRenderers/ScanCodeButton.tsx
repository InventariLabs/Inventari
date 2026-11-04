import { useState } from "react";
import { Camera } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { ScanCameraPanel } from "@/module-sdk";
import { useScanCamera } from "@/hooks/useScanCamera";

interface ScanCodeButtonProps {
  /** What the button says: which field the camera fills. */
  label: string;
  /** The code the camera read, for the field it belongs to. */
  onCode: (code: string) => void;
  /** See `ScanCameraPanel`: keep the viewfinder in view while the page scrolls. */
  pinned?: boolean;
}

/**
 * A button that opens the camera to fill one field from a printed code.
 *
 * One read fills the field and puts the camera away: a field holds one code,
 * and a camera left running would overwrite a correction.
 */
export function ScanCodeButton({
  label,
  onCode,
  pinned = false,
}: ScanCodeButtonProps) {
  const [open, setOpen] = useState(false);
  const close = () => {
    camera.setIsCameraActive(false);
    setOpen(false);
  };
  const camera = useScanCamera({
    onCodeScanned: (code) => {
      onCode(code.trim());
      close();
    },
  });

  return (
    <>
      <Button
        type="button"
        variant="outline"
        size="sm"
        leftIcon={<Camera size={16} />}
        aria-pressed={open}
        onClick={() => {
          if (open) return close();
          camera.restartCamera();
          setOpen(true);
        }}
      >
        {label}
      </Button>
      <ScanCameraPanel
        open={open}
        pinned={pinned}
        scannerError={camera.scannerError}
        isCameraActive={camera.isCameraActive}
        isTorchOn={camera.isTorchOn}
        onRetry={camera.restartCamera}
        onToggleTorch={camera.toggleTorch}
        onClose={close}
      />
    </>
  );
}
