import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Camera, ScanLine } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { ScanCameraPanel } from "@/components/ui/ScanCameraPanel";
import { useScanCamera } from "@/hooks/useScanCamera";
import { useScannerInput } from "@/hooks/useScannerInput";

/**
 * One field for a code the worker reads off a label: typed, sent by a
 * hardware scanner, or read by the camera. The screens that use it answer
 * the code themselves.
 */
export default function ScanField({
  prompt,
  disabled = false,
  onCode,
}: {
  prompt: string;
  disabled?: boolean;
  onCode: (code: string) => void;
}) {
  const { t } = useTranslation("warehouse");
  const [code, setCode] = useState("");
  const [cameraOpen, setCameraOpen] = useState(false);
  const camera = useScanCamera({ onCodeScanned: onCode });
  // A hardware scanner types into whatever has the focus and presses Enter.
  useScannerInput(
    (scanned) => {
      setCode("");
      onCode(scanned);
    },
    { enabled: !disabled },
  );

  return (
    <div className="space-y-2">
      <form
        onSubmit={(event) => {
          event.preventDefault();
          if (!code.trim()) return;
          onCode(code.trim());
          setCode("");
        }}
      >
        <Input
          label={prompt}
          labelClassName="sr-only"
          placeholder={prompt}
          value={code}
          onChange={(event) => setCode(event.target.value)}
          leftIcon={<ScanLine size={16} />}
          autoComplete="off"
          disabled={disabled}
          data-scanner-input=""
          data-scanner-whole=""
        />
      </form>
      <Button
        variant="outline"
        size="lg"
        className="w-full"
        leftIcon={<Camera size={16} />}
        aria-pressed={cameraOpen}
        onClick={() => {
          if (cameraOpen) {
            camera.setIsCameraActive(false);
            setCameraOpen(false);
            return;
          }
          camera.restartCamera();
          setCameraOpen(true);
        }}
      >
        {cameraOpen ? t("scan.close") : t("scan.open")}
      </Button>
      <ScanCameraPanel
        open={cameraOpen}
        scannerError={camera.scannerError}
        isCameraActive={camera.isCameraActive}
        isTorchOn={camera.isTorchOn}
        onRetry={camera.restartCamera}
        onToggleTorch={camera.toggleTorch}
        onClose={() => {
          camera.setIsCameraActive(false);
          setCameraOpen(false);
        }}
      />
    </div>
  );
}
