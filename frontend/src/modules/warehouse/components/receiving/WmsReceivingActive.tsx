import { useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { X, ScanLine, CheckCircle2, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { Sheet, SheetActions, SheetFooter } from "@/components/ui/Sheet";
import { Input } from "@/components/ui/Input";
import { QuantityInput } from "@/components/ui/QuantityInput";
import { ScannerReadyHint } from "@/components/ui/ScannerReadyHint";
import { ScanCameraPanel } from "@/components/ui/ScanCameraPanel";
import { useScannerInput } from "@/hooks/useScannerInput";
import { useScanCamera } from "@/hooks/useScanCamera";
import { unitLabel } from "@/lib/i18nHelpers";
import type {
  WmsReceiveLine,
  WmsReceiveSession,
} from "@/modules/warehouse/api/documents_receiving";
import WmsReceiveLineRow from "./WmsReceiveLineRow";
import { shelfConfirmationState } from "../ShelfConfirmation";
import { formatQuantityValue } from "@/utils/formatters";

interface Props {
  session: WmsReceiveSession;
  lines: WmsReceiveLine[];
  isLoading: boolean;
  error: string | null;
  onScan: (barcode: string, quantity: number) => void;
  onUndoLine: (line: WmsReceiveLine) => void;
  onFullReceive: (line: WmsReceiveLine) => void;
  onShortReceive: (line: WmsReceiveLine) => void;
  onSkipLine: (line: WmsReceiveLine) => void;
  /** Shelves the worker may re-aim a pending line at. */
  targetChangePending?: boolean;
  onTargetChange?: (line: WmsReceiveLine, target: string | null) => void;
  onComplete: () => void;
  onCancel: () => void;
  onClose: () => void;
}

export default function WmsReceivingActive({
  session,
  lines,
  isLoading,
  error,
  onScan,
  onUndoLine,
  onFullReceive,
  onShortReceive,
  onSkipLine,
  targetChangePending,
  onTargetChange,
  onComplete,
  onCancel,
  onClose,
}: Props) {
  const { t } = useTranslation(["warehouse", "common"]);
  const barcodeRef = useRef<HTMLInputElement>(null);
  const [quantity, setQuantity] = useState("1");
  const [cameraOpen, setCameraOpen] = useState(false);
  // A code the camera reads takes the same path as one typed and confirmed.
  const camera = useScanCamera({ onCodeScanned: (code) => submitScan(code) });

  const receivableLines = lines.filter((ln) => ln.status !== "skipped");
  const receivedCount = lines.filter(
    (ln) => ln.status === "received" || ln.status === "short",
  ).length;
  const pendingLines = lines.filter((ln) => ln.status === "pending");
  // Throwing the scans away asks first once the session holds any work: on
  // a phone one stray tap would otherwise empty it.
  const [discardAsk, setDiscardAsk] = useState(false);
  const hasWork = lines.some(
    (ln) => ln.received_quantity > 0 || ln.status === "short",
  );

  const nextLine = pendingLines[0];
  const unitSymbol = nextLine?.uom_symbol;

  const openCamera = () => {
    // Already open and working: the camera is the answer, not another start.
    // An open panel showing a refusal is retried, because on a phone this
    // button is what the receiver reaches for after allowing the camera.
    if (cameraOpen && !camera.scannerError) return;
    camera.restartCamera();
    setCameraOpen(true);
  };

  const closeCamera = () => {
    camera.setIsCameraActive(false);
    setCameraOpen(false);
  };

  // A code from a hardware scanner or the camera takes the same path as one
  // typed into the field and confirmed.
  const submitScan = (scanned?: string) => {
    const barcode = (scanned ?? barcodeRef.current?.value)?.trim();
    const qty = Number(quantity) || 1;
    if (!barcode) {
      // The field is empty: the button opens the camera instead of doing
      // nothing, and the panel itself says why a refused camera refused.
      openCamera();
      return;
    }
    onScan(barcode, qty);
    if (barcodeRef.current) barcodeRef.current.value = "";
    setQuantity("1");
  };
  useScannerInput(submitScan, { enabled: Boolean(nextLine) });

  return (
    <Sheet
      open
      onClose={onClose}
      zIndex="modal"
      maxWidth="md"
      fullBleedOnMobile
      aria-label={t("receiving.title")}
    >
      <div className="flex items-center justify-between px-4 pt-[calc(env(safe-area-inset-top)+0.75rem)] pb-3 border-b border-border shrink-0 bg-surface-card">
        <div className="min-w-0">
          <h2 className="text-sm font-semibold text-on truncate">
            {t("receiving.title")}
          </h2>
          <p className="text-xs text-on-secondary">
            {receivedCount}/{receivableLines.length} {t("receiving.progress")}
          </p>
        </div>
        <Button
          onClick={onClose}
          variant="ghost"
          // The way out of a full-screen sheet, in the corner a thumb reaches
          // last: the 44 px target, not the compact one of a row.
          size="icon"
          className="text-on-muted hover:text-on-secondary shrink-0 ml-2"
          aria-label={t("common:a11y.close")}
        >
          <X size={18} />
        </Button>
      </div>

      {nextLine && (
        <div className="px-4 py-2 bg-surface border-b border-border shrink-0">
          {/* the barcode field is the point of the screen — full
              width row; quantity + scan action move to a second line. */}
          <div className="flex flex-col gap-2">
            <Input
              ref={barcodeRef}
              type="text"
              aria-label={t("receiving.scan_prompt")}
              placeholder={t("receiving.scan_prompt")}
              className="w-full rounded-xl border border-border bg-surface-card px-3 py-2 text-sm placeholder:text-on-muted focus:outline-none focus:ring-2 focus:ring-primary-500"
              onKeyDown={(e) => {
                if (e.key === "Enter") submitScan();
              }}
              data-scanner-input=""
              data-scanner-whole=""
              autoFocus
            />
            <div className="flex items-center gap-2">
              {/* The unit decides the step, not this screen. It used to be
                  hardcoded, and the four quantity fields of this module
                  between them carried four different answers. */}
              <QuantityInput
                wrapperClassName="w-24"
                uomSymbol={unitSymbol}
                value={quantity}
                onChange={(e) => setQuantity(e.target.value)}
                className="rounded-xl border border-border bg-surface-card px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary-500"
                aria-label={t("receiving.quantity")}
                // A scan taken while this field has the focus is still the
                // barcode's; what was typed here stays.
                data-scanner-keep=""
              />
              <Button
                type="button"
                variant="default"
                size="sm"
                className="flex-1 rounded-xl shadow-none"
                onClick={() => submitScan()}
              >
                <ScanLine size={16} />
                <span>{t("receiving.scanAction")}</span>
              </Button>
            </div>
          </div>
          <ScannerReadyHint className="mt-1.5" />
          <ScanCameraPanel
            open={cameraOpen}
            scannerError={camera.scannerError}
            isCameraActive={camera.isCameraActive}
            isTorchOn={camera.isTorchOn}
            onRetry={camera.restartCamera}
            onToggleTorch={camera.toggleTorch}
            onClose={closeCamera}
            className="mt-2"
          />
          {/* A line part of which has already arrived stays the next one to
              scan, so naming only what was ordered would put "12.5 kg" above a
              field whose job is now to take the remaining 7.5. */}
          <p className="mt-1 text-sm text-on-secondary">
            {nextLine.product_name} —{" "}
            {nextLine.received_quantity > 0
              ? `${formatQuantityValue(nextLine.received_quantity)}/${formatQuantityValue(
                  nextLine.expected_quantity,
                )}`
              : formatQuantityValue(nextLine.expected_quantity)}{" "}
            {unitLabel(t, nextLine.uom_symbol)}
          </p>
        </div>
      )}

      {error && (
        <div className="px-4 py-2 bg-red-50 text-sm text-red-600 shrink-0">
          {error}
        </div>
      )}

      <div className="flex-1 overflow-y-auto">
        {/* Skipped lines stay: hidden, they could not be taken back. */}
        {lines.map((ln) => (
          <WmsReceiveLineRow
            key={ln.id}
            line={ln}
            // Only a shelf with a code to scan is asked for, as the session
            // asks: the hint for a codeless one would promise a label that
            // does not exist.
            shelfState={shelfConfirmationState(
              session,
              ln.planned_location_code ? ln.planned_location_id : null,
            )}
            onUndo={onUndoLine}
            onFullReceive={onFullReceive}
            onShortReceive={onShortReceive}
            onSkip={onSkipLine}
            targetLocationId={ln.target_location_id ?? null}
            targetChangePending={targetChangePending}
            onTargetChange={onTargetChange}
          />
        ))}
      </div>

      <SheetFooter>
        <SheetActions>
          <Button
            variant="outline"
            onClick={() => (hasWork ? setDiscardAsk(true) : onCancel())}
            disabled={isLoading}
            className="text-red-600 border-red-200 hover:bg-red-50"
          >
            {isLoading ? (
              <Loader2 size={14} className="animate-spin" />
            ) : (
              t("receiving.cancel")
            )}
          </Button>
          <Button
            onClick={onComplete}
            // only unresolved lines block finishing. Requiring at least
            // one received/picked line left a session where everything was
            // skipped with no way out but Cancel — which means something else.
            disabled={isLoading || pendingLines.length > 0}
            className="gap-1"
          >
            {isLoading ? (
              <Loader2 size={14} className="animate-spin" />
            ) : (
              <>
                <CheckCircle2 size={14} />
                {t("receiving.complete")}
              </>
            )}
          </Button>
        </SheetActions>
      </SheetFooter>

      <ConfirmDialog
        open={discardAsk}
        variant="danger"
        title={t("receiving.discard_confirm_title")}
        message={t("receiving.discard_confirm_message")}
        confirmLabel={t("receiving.cancel")}
        onConfirm={() => {
          setDiscardAsk(false);
          onCancel();
        }}
        onCancel={() => setDiscardAsk(false)}
      />
    </Sheet>
  );
}
