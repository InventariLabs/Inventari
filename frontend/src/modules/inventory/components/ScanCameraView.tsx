import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  X,
  Camera,
  Zap,
  ZapOff,
  RefreshCcw,
  Info,
  Keyboard,
} from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { DynamicIcon } from "@/components/ui/DynamicIcon";
import { ScannerReadyHint } from "@/components/ui/ScannerReadyHint";
import { useMediaQuery } from "@/hooks/useMediaQuery";
import { useTorchAvailable } from "@/module-sdk";
import { useScannerInput } from "@/hooks/useScannerInput";
import type { StorageContext } from "@/store/scanStore";
interface ScanCameraViewProps {
  isCameraActive: boolean;
  scannerError: string | null;
  isTorchOn: boolean;
  storageContext: StorageContext | null;
  onBack: () => void;
  onStartCamera: () => void;
  onRestartCamera: () => void;
  onToggleTorch: () => void;
  onClearStorageContext: () => void;
  onManualCode?: (code: string) => void;
  /**
   * Why the last code was refused, kept on screen until the next attempt or
   * a dismiss: a toast went away in seconds, and on a wide screen the page
   * underneath it is the one thing the reader looks at.
   */
  lookupFailure?: LookupFailure | null;
  onDismissLookupFailure?: () => void;
}

export interface LookupFailure {
  code: string;
  message: string;
  /** Where the typed code can be searched for, when nothing recognized it. */
  onSearch?: () => void;
}

/**
 * Typing a barcode instead of scanning it. Reachable from every state where
 * the camera is not delivering codes — including the error overlay, which
 * used to cover the only copy of this field and leave a phone user stuck.
 */
function ManualCodeEntry({ onSubmit }: { onSubmit: (code: string) => void }) {
  const { t: tScan } = useTranslation(["scan", "common"]);
  const [value, setValue] = useState("");
  // A USB scanner at a desktop types into the field without a click first; on
  // a phone the focus would open a keyboard over the camera.
  const isDesktop = useMediaQuery("(min-width: 768px)");
  const inputRef = useRef<HTMLInputElement>(null);
  useEffect(() => {
    if (isDesktop) inputRef.current?.focus();
  }, [isDesktop]);

  const submit = () => {
    const code = value.trim();
    if (!code) return;
    onSubmit(code);
    setValue("");
  };

  return (
    <div className="mt-8 w-full max-w-sm">
      <div className="flex items-center gap-2 mb-3 text-on-muted text-xs font-medium uppercase tracking-widest justify-center">
        <Keyboard size={14} />
        {tScan("manualInputLabel")}
      </div>
      <div className="flex gap-2">
        <Input
          type="text"
          aria-label={tScan("manualInputLabel")}
          data-testid="manual-barcode-input"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") submit();
          }}
          placeholder={tScan("manualInputPlaceholder")}
          ref={inputRef}
        />
        <Button variant="outline" onClick={submit} className="shrink-0">
          {tScan("manualInputSubmit")}
        </Button>
      </div>
      {/* The app reads three different code spaces and told the reader which
          one it wanted only after they had submitted the wrong one. */}
      <p className="mt-2 text-xs text-on-muted text-center">
        {tScan("manualInputHint")}
      </p>
      {/* The view listens for a USB or Bluetooth scanner, so a code it reads
          needs no field at all. */}
      <ScannerReadyHint className="mt-2 justify-center" />
    </div>
  );
}

export default function ScanCameraView({
  isCameraActive,
  scannerError,
  isTorchOn,
  storageContext,
  onBack,
  onStartCamera,
  onRestartCamera,
  onToggleTorch,
  onClearStorageContext,
  onManualCode,
  lookupFailure,
  onDismissLookupFailure,
}: ScanCameraViewProps) {
  const { t: tScan } = useTranslation(["scan", "common"]);
  const hasTorch = useTorchAvailable();
  // A hardware scanner's code takes the camera's path, from any state.
  useScannerInput((code) => onManualCode?.(code), {
    enabled: Boolean(onManualCode),
  });

  return (
    // The video keeps its own shape (width fills, height follows): html5-qrcode
    // maps the decode region onto the picture assuming it is scaled, not
    // cropped, so forcing it to cover the screen sent the decoder a slice
    // that differs from what the frame shows.
    <div className="flex-1 relative overflow-hidden bg-black [&_#qr-reader>div]:!border-0 [&_#qr-reader>div]:!bg-transparent [&_canvas]:!bg-transparent">
      <div
        id="qr-reader"
        className="absolute inset-0 w-full h-full bg-black z-0 shadow-inner flex flex-col justify-center overflow-hidden"
      ></div>

      {/* The aim frame: the video is centred in #qr-reader and so is the
          region html5-qrcode decodes, whose size the camera hook publishes as
          --aim-w / --aim-h. Drawn from them, the frame cannot drift from it. */}
      {!scannerError && isCameraActive && (
        <div
          data-testid="scan-aim-frame"
          className="absolute left-1/2 top-1/2 z-10 -translate-x-1/2 -translate-y-1/2 pointer-events-none rounded-2xl border border-white/80 w-[var(--aim-w,0px)] h-[var(--aim-h,0px)] shadow-[0_0_0_9999px_rgba(0,0,0,0.45)]"
        />
      )}

      {/* HUD: Top Controls */}
      <div className="absolute top-6 left-0 right-0 z-30 px-6 flex items-start justify-between pointer-events-none">
        <div className="flex flex-col gap-3 pointer-events-auto">
          <Button
            variant="secondary"
            size="icon"
            onClick={onBack}
            className="rounded-full bg-black/40 backdrop-blur-xl border-white/10 text-white hover:bg-black/60"
            aria-label={tScan("common:a11y.goBack")}
          >
            <X size={24} />
          </Button>
        </div>

        {/* Storage Context Bubble */}
        {storageContext && (
          <div className="bg-black/40 backdrop-blur-xl border border-white/10 rounded-full px-4 py-2 flex items-center gap-3 animate-in slide-in-from-top-4 duration-500 pointer-events-auto">
            <div className="w-8 h-8 bg-accent-500 rounded-full flex items-center justify-center text-white shadow-lg shadow-accent-500/20">
              <DynamicIcon
                name={storageContext.icon}
                size={18}
                strokeWidth={2.5}
              />
            </div>
            <div className="min-w-0 pr-2">
              <p className="text-[10px] font-medium text-accent-400 uppercase tracking-widest leading-none mb-0.5">
                {tScan("storageContextTitle")}
              </p>
              <p className="text-white font-medium text-xs truncate max-w-[120px]">
                {storageContext.name}
              </p>
            </div>
            <Button
              variant="ghost"
              size="iconSm"
              onClick={onClearStorageContext}
              aria-label={tScan("clearStorageContext")}
              className="hover:bg-surface-card/10 rounded-full text-white/40 hover:text-white"
            >
              <X size={14} />
            </Button>
          </div>
        )}

        {hasTorch && (
          <div className="flex flex-col gap-3 pointer-events-auto">
            <Button
              variant="secondary"
              size="icon"
              onClick={onToggleTorch}
              aria-label={tScan(isTorchOn ? "torchOff" : "torchOn")}
              className={`rounded-full backdrop-blur-xl border-white/10 transition-all ${
                isTorchOn
                  ? "bg-amber-400 text-black shadow-lg shadow-amber-400/20"
                  : "bg-black/40 text-white"
              }`}
            >
              {isTorchOn ? (
                <Zap size={24} fill="currentColor" />
              ) : (
                <ZapOff size={24} />
              )}
            </Button>
          </div>
        )}
      </div>

      {lookupFailure && (
        <div
          role="alert"
          data-testid="scan-lookup-failure"
          className="absolute inset-x-0 top-0 z-[60] m-3 flex flex-col gap-2 rounded-xl border border-red-200 bg-surface-card p-4 text-left shadow-lg"
        >
          <p className="font-mono text-sm font-semibold text-on break-all">
            {lookupFailure.code}
          </p>
          <p className="text-sm text-on-secondary">{lookupFailure.message}</p>
          <div className="flex flex-wrap gap-2">
            {lookupFailure.onSearch && (
              <Button size="sm" onClick={lookupFailure.onSearch}>
                {tScan("searchForCode")}
              </Button>
            )}
            <Button
              size="sm"
              variant="outline"
              onClick={onDismissLookupFailure}
            >
              {tScan("common:actions.close")}
            </Button>
          </div>
        </div>
      )}

      {/* Desktop Mode / Camera Not Active Overlay */}
      {!isCameraActive && !scannerError && (
        <div className="absolute inset-0 z-50 bg-surface flex flex-col items-center justify-center p-10 text-center animate-in fade-in">
          <div className="w-32 h-32 bg-surface-card text-primary-600 rounded-2xl flex items-center justify-center mb-10 shadow-md ring-1 ring-gray-100">
            <Camera size={64} strokeWidth={1.2} />
          </div>
          <h3 className="text-on font-semibold text-xl mb-4 tracking-tight">
            {tScan("desktopTitle")}
          </h3>
          <p className="text-on-secondary text-lg max-w-sm mb-12 font-medium leading-relaxed">
            {tScan("desktopDesc")}
          </p>
          <Button
            size="lg"
            onClick={onStartCamera}
            className="h-16 px-12 text-xl"
            leftIcon={<Camera size={24} />}
          >
            {tScan("startCamera")}
          </Button>
          {onManualCode && <ManualCodeEntry onSubmit={onManualCode} />}
        </div>
      )}

      {/* Error Overlay */}
      {scannerError && (
        <div className="absolute inset-0 z-50 bg-surface-card/95 backdrop-blur-xl flex flex-col items-center justify-center p-10 text-center animate-in fade-in">
          <div className="w-20 h-20 bg-red-50 text-red-500 rounded-xl flex items-center justify-center mb-6 shadow-sm">
            <X size={40} />
          </div>
          <h3 className="text-on font-semibold text-2xl mb-3 leading-tight">
            {tScan("errorCamera")}
          </h3>
          <p className="text-on-secondary font-medium max-w-xs mb-3 leading-relaxed">
            {scannerError}
          </p>
          {/* Every cause above leads somewhere else — a permission, an
              address, a device — and this is the one way through that works
              for all of them. The field itself is right below. */}
          <p className="text-on-muted text-sm max-w-xs mb-10 leading-relaxed">
            {tScan("errorCameraManualHint")}
          </p>
          <Button
            variant="outline"
            size="lg"
            onClick={onRestartCamera}
            className="h-14 px-10 rounded-2xl border"
            leftIcon={<RefreshCcw size={20} />}
          >
            {tScan("retry")}
          </Button>
          {onManualCode && <ManualCodeEntry onSubmit={onManualCode} />}
        </div>
      )}

      {!scannerError && isCameraActive && (
        <div className="absolute inset-x-0 bottom-0 z-20 pointer-events-none flex flex-col items-center pb-8 px-4">
          <div className="flex flex-col items-center gap-4 animate-in fade-in slide-in-from-bottom-2 duration-1000">
            <p
              data-testid="scan-instructions"
              className="text-white font-medium text-xs tracking-[0.3em] uppercase bg-black/40 backdrop-blur-xl px-8 py-4 rounded-full border border-white/10 shadow-lg"
            >
              {tScan("aimAtCode")}
            </p>
            <div className="flex items-center gap-2 text-white/40 text-[10px] font-medium uppercase tracking-widest">
              <Info size={12} />
              {tScan("supportedFormatsHint")}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
