import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import {
  Camera,
  CameraOff,
  Search,
  AlertCircle,
  Loader2,
  RefreshCcw,
  Zap,
} from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { Card } from "@/components/ui/Card";
import { ScannerReadyHint } from "@/components/ui/ScannerReadyHint";
import { useScanCamera } from "@/hooks/useScanCamera";
import { useScanResolver } from "@/hooks/useScanResolver";
import { useScannerInput } from "@/hooks/useScannerInput";
import {
  documentScanTarget,
  searchForCodeTarget,
} from "@/lib/scan/scanSubject";
import { useDocumentProfile } from "@/modules/warehouse/hooks/useDocumentProfile";
import { exampleReceiptNumber } from "@/modules/warehouse/lib/exampleNumber";
import { LocationContentsSheet } from "@/modules/shared/components/LocationContentsSheet";

export default function DocumentScanPage() {
  const { t } = useTranslation("warehouse");
  const { t: tScan } = useTranslation("scan");
  const navigate = useNavigate();
  const [manualNumber, setManualNumber] = useState("");
  // The code nothing recognized: the card says so and offers it to the search.
  const [missedCode, setMissedCode] = useState<string | null>(null);
  const [cameraAvailable, setCameraAvailable] = useState<boolean>(true);
  const [location, setLocation] = useState<{ id: string; name: string } | null>(
    null,
  );
  // The example under the manual field is written from the organization's own
  // numbering format — the same cached read the settings and register do.
  const { data: profile } = useDocumentProfile();

  useEffect(() => {
    let cancelled = false;
    const probe = async () => {
      const md = navigator.mediaDevices;
      if (!md || typeof md.enumerateDevices !== "function") {
        if (!cancelled) setCameraAvailable(false);
        return;
      }
      try {
        const devices = await md.enumerateDevices();
        const hasVideo = devices.some((d) => d.kind === "videoinput");
        if (!cancelled) setCameraAvailable(hasVideo);
      } catch {
        if (!cancelled) setCameraAvailable(false);
      }
    };
    void probe();
    return () => {
      cancelled = true;
    };
  }, []);

  // The read goes through the same registry as every other scanning
  // screen. This screen used to look documents up by number on its own, so a
  // label, a location or a product code landed on "document not found" —
  // and its own printed QR, which wraps the number in a `?code=` URL, would
  // not have resolved at all, because the unwrapping lives in the registry.
  const { resolve, isResolving } = useScanResolver({
    handle: (result) => {
      // A location label answers what is on the place, not "not a document".
      if (result.action === "set_storage_context" && result.location) {
        if ("vibrate" in navigator) navigator.vibrate(100);
        setMissedCode(null);
        setLocation(result.location);
        return true;
      }
      const target = documentScanTarget(result);
      if (!target) return false;
      if ("vibrate" in navigator) navigator.vibrate(100);
      setMissedCode(null);
      navigate(target);
      return true;
    },
    acceptUnrecognized: (code) => {
      setMissedCode(code);
      return true;
    },
  });

  const {
    scannerError,
    isCameraActive,
    isCameraRunning,
    setIsCameraActive,
    restartCamera,
    toggleTorch,
  } = useScanCamera({
    onCodeScanned: (code) => void resolve(code),
  });
  // A hardware scanner reads the same codes the camera does. What it typed
  // into the field, if it had the focus, is the scan itself, not a draft.
  useScannerInput((code) => {
    setManualNumber("");
    void resolve(code);
  });

  // The switch shows what the device is doing, and does what it shows. While
  // the camera is refusing, it reads as off and pressing it asks the device
  // again — instead of a blue "Skanowanie…" over the refusal, which is what
  // the wish to scan painted there.
  const handleCameraSwitch = () => {
    if (isCameraRunning) setIsCameraActive(false);
    else if (isCameraActive) restartCamera();
    else setIsCameraActive(true);
  };

  const handleManualSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    void resolve(manualNumber);
  };

  return (
    <div className="space-y-6">
      {/* Empty state — only while camera is off and we have no lookup error */}
      {!isCameraActive && !scannerError && (
        <div
          data-testid="scan-empty-state"
          className="rounded-xl border border-dashed border-border bg-surface-raised/40 px-4 py-5 text-sm text-on-secondary"
        >
          <p className="font-medium text-on">{t("scan.emptyTitle")}</p>
          <p className="mt-1">{t("scan.emptyHint")}</p>
        </div>
      )}

      {/* No-camera fallback — surfaces when the browser does not expose
          a videoinput device (insecure context, desktop without a webcam,
          permission denied by browser policy). Hides the camera toggle
          and redirects the user straight to the manual entry path. */}
      {!cameraAvailable && !scannerError && (
        <div
          data-testid="scan-no-camera-fallback"
          className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900 dark:border-amber-700 dark:bg-amber-950/30 dark:text-amber-200"
        >
          <p className="font-medium">{t("scan.noCameraTitle")}</p>
          <p className="mt-1 text-amber-800 dark:text-amber-300">
            {t("scan.noCameraHint")}
          </p>
        </div>
      )}

      {/* Camera / Manual toggle */}
      <div className="flex gap-2">
        <Button
          variant={isCameraRunning ? "default" : "outline"}
          size="sm"
          leftIcon={
            isCameraRunning ? <CameraOff size={16} /> : <Camera size={16} />
          }
          onClick={handleCameraSwitch}
        >
          {isCameraRunning ? t("scan.scanning") : t("scan.title")}
        </Button>
        {isCameraActive && (
          <Button
            variant="outline"
            size="icon"
            onClick={toggleTorch}
            aria-label={t("scan.toggleTorch")}
          >
            <Zap size={16} />
          </Button>
        )}
      </div>

      {/* Camera view. html5-qrcode makes the reader `position: relative`
          when it starts, so the reader keeps this box's size by width and
          height, and the picture is centred in it, as is the region the
          library decodes. Its own shading is sized for the whole picture,
          which the box crops, so it is switched off; the frame is drawn from
          --aim-w / --aim-h, the size the camera hook publishes for that
          region. The box is as tall as 4:3 makes it, up to what is left of the
          window under the bars and the controls: in a low window the whole
          aiming frame is then on screen without scrolling. The cap has a
          floor: with the keyboard open the window is a few hundred pixels
          and the cap would reach 0, collapsing the view under the 50 px
          html5-qrcode needs for its box (it throws). 4rem is the smallest
          box whose frame (90% of its height, 57 px) clears that minimum, and
          it stays under the ~104 px a 360 px-high phone leaves, so the frame
          still fits there. */}
      {isCameraActive && (
        <div className="relative aspect-[4/3] w-full max-h-[max(4rem,calc(100dvh-16rem))] rounded-xl overflow-hidden bg-black [&_#qr-reader>div]:!border-0 [&_#qr-reader>div]:!bg-transparent">
          <div
            id="qr-reader"
            className="absolute inset-0 h-full w-full flex flex-col justify-center"
          />
          {!scannerError && (
            <div
              data-testid="scan-aim-frame"
              className="absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 pointer-events-none rounded-2xl border border-white/80 w-[var(--aim-w,0px)] h-[var(--aim-h,0px)] shadow-[0_0_0_9999px_rgba(0,0,0,0.45)]"
            />
          )}
          {scannerError && (
            <div className="absolute inset-0 flex items-center justify-center bg-black/80">
              <div className="text-center text-white space-y-3 p-4">
                <AlertCircle size={32} className="mx-auto text-red-400" />
                <p className="text-sm">{scannerError}</p>
                {/* The field below the camera takes the code by hand, and it
                    is the way through whatever the cause was. */}
                <p className="text-xs text-white/70">
                  {t("scan:errorCameraManualHint")}
                </p>
                <Button variant="secondary" size="sm" onClick={restartCamera}>
                  <RefreshCcw size={16} className="mr-1" />
                  {t("scan:retry")}
                </Button>
              </div>
            </div>
          )}
          {/* Below the frame: the frame leaves a tenth of the box's width
              under it, and a line any higher crosses its bottom edge. */}
          {!scannerError && (
            <div className="absolute inset-0 flex items-end justify-center pb-2 pointer-events-none">
              <p className="text-white/60 text-xs">{t("scan.aimText")}</p>
            </div>
          )}
        </div>
      )}

      {/* Manual input */}
      <div className="space-y-1.5">
        <form onSubmit={handleManualSubmit} className="flex gap-2">
          <Input
            wrapperClassName="flex-1"
            aria-label={t("scan.placeholder")}
            value={manualNumber}
            onChange={(e) => setManualNumber(e.target.value)}
            placeholder={t("scan.placeholder")}
            leftIcon={<Search size={15} />}
            data-scanner-input=""
          />
          <Button
            type="submit"
            size="sm"
            disabled={isResolving || !manualNumber.trim()}
          >
            {isResolving ? (
              <Loader2 size={16} className="animate-spin" />
            ) : (
              t("scan.search")
            )}
          </Button>
        </form>
        {/* This field reads document numbers, not barcodes — which the screen
            said only by rejecting what was typed. */}
        <p className="text-xs text-on-muted">
          {t("scan.numberHint", {
            example: exampleReceiptNumber({
              numberingFormat: profile?.numbering_format,
              numberPadding: profile?.number_padding,
              receiptLabel: profile?.type_labels?.IN,
            }),
          })}
        </p>
        <ScannerReadyHint />
      </div>

      {/* Error state */}
      {missedCode && (
        <Card className="p-4 border-red-200 bg-red-50">
          <div className="flex items-start gap-3">
            <AlertCircle size={20} className="text-red-500 shrink-0 mt-0.5" />
            <div>
              <p className="font-medium text-red-700">{t("scan.notFound")}</p>
              <p className="text-sm text-red-700 mt-0.5">
                {t("scan.notFoundDesc")}
              </p>
              <Button
                variant="outline"
                size="sm"
                className="mt-2"
                leftIcon={<Search size={16} />}
                onClick={() => navigate(searchForCodeTarget(missedCode))}
              >
                {tScan("searchForCode")}
              </Button>
            </div>
          </div>
        </Card>
      )}

      {location && (
        <LocationContentsSheet
          location={location}
          offerLabel
          onClose={() => setLocation(null)}
        />
      )}
    </div>
  );
}
