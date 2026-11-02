import { useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { X, CheckCircle2, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { Sheet, SheetActions, SheetFooter } from "@/components/ui/Sheet";
import { Input } from "@/components/ui/Input";
import { useScannerInput } from "@/hooks/useScannerInput";
import { useScanCamera } from "@/hooks/useScanCamera";
import type {
  WmsPickLine,
  WmsPickSession,
} from "@/modules/warehouse/api/documents";
import { PickListButton } from "./PickListButton";
import WmsPickLineRow from "./WmsPickLineRow";
import WmsPickStep from "./WmsPickStep";
import WmsPickDocumentProgress from "./WmsPickDocumentProgress";
import { groupLinesByDocument } from "./documentGroups";
import {
  awaitsDestination,
  shelfConfirmationState,
} from "../ShelfConfirmation";

interface Props {
  session: WmsPickSession;
  lines: WmsPickLine[];
  isLoading: boolean;
  error: string | null;
  /** What the last refused scan said, until the next scan answers. */
  refusal?: string | null;
  onScan: (barcode: string, quantity: number, lotName?: string) => void;
  onFullPick: (line: WmsPickLine) => void;
  onUndoLine: (line: WmsPickLine) => void;
  onShortPick: (line: WmsPickLine) => void;
  onSkipLine: (line: WmsPickLine) => void;
  onComplete: () => void;
  onCancel: () => void;
  onClose: () => void;
}

export default function WmsPickingActive({
  session,
  lines,
  isLoading,
  error,
  refusal,
  onScan,
  onFullPick,
  onUndoLine,
  onShortPick,
  onSkipLine,
  onComplete,
  onCancel,
  onClose,
}: Props) {
  const { t } = useTranslation(["warehouse", "common"]);
  const barcodeRef = useRef<HTMLInputElement>(null);
  const lotRef = useRef<HTMLInputElement>(null);
  const [quantity, setQuantity] = useState("1");
  const [cameraOpen, setCameraOpen] = useState(false);
  // A code the camera reads takes the same path as one typed and confirmed.
  const camera = useScanCamera({ onCodeScanned: (code) => submitScan(code) });

  const pickableLines = lines.filter((ln) => ln.status !== "skipped");
  const pickedCount = lines.filter(
    (ln) => ln.status === "picked" || ln.status === "short",
  ).length;
  const pendingLines = lines.filter((ln) => ln.status === "pending");
  // Throwing the scans away asks first once the session holds any work: on
  // a phone one stray tap would otherwise empty it.
  const [discardAsk, setDiscardAsk] = useState(false);
  const hasWork = lines.some(
    (ln) => ln.picked_quantity > 0 || ln.status === "short",
  );
  const isMultiDocument = session.documents.length > 1;

  const nextLine = pendingLines[0];
  // Every line answered on a transfer that confirms its destination: the
  // sheet asks for that label instead of another product.
  const awaitingDestination = awaitsDestination(session, lines);

  const openCamera = () => {
    // Already open and working: the camera is the answer, not another start.
    // An open panel showing a refusal is retried, because on a phone this
    // button is what the picker reaches for after allowing the camera.
    if (cameraOpen && !camera.scannerError) return;
    camera.restartCamera();
    setCameraOpen(true);
  };

  const closeCamera = () => {
    camera.setIsCameraActive(false);
    setCameraOpen(false);
  };

  // One scan is one handling. Receiving has always asked how much; picking
  // closed the whole line on the first scan, so a picker holding one of four
  // reported four.
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
    onScan(barcode, qty, lotRef.current?.value.trim() || undefined);
    if (barcodeRef.current) barcodeRef.current.value = "";
    if (lotRef.current) lotRef.current.value = "";
    setQuantity("1");
  };
  useScannerInput(submitScan, {
    enabled: Boolean(nextLine) || awaitingDestination,
  });

  return (
    <Sheet
      open
      onClose={onClose}
      zIndex="modal"
      maxWidth="md"
      fullBleedOnMobile
      aria-label={t("picking.title")}
    >
      <div className="flex items-center justify-between px-4 pt-[calc(env(safe-area-inset-top)+0.75rem)] pb-3 border-b border-border shrink-0 bg-surface-card">
        <div className="min-w-0">
          <p className="text-sm font-semibold text-on truncate">
            {t("picking.title")}
          </p>
          <p className="text-xs text-on-secondary">
            {pickedCount}/{pickableLines.length} {t("picking.progress")}
          </p>
        </div>
        <div className="flex items-center shrink-0">
          <PickListButton
            documentId={session.document_id}
            sessionId={session.id}
            number={
              session.documents[0]?.document_number ?? session.document_id
            }
            iconOnly
          />
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
      </div>

      {isMultiDocument && (
        <WmsPickDocumentProgress
          groups={groupLinesByDocument(session, lines)}
        />
      )}

      {(nextLine || awaitingDestination) && (
        <WmsPickStep
          session={session}
          line={nextLine ?? null}
          awaitingDestination={awaitingDestination}
          showDocument={isMultiDocument}
          scanField={
            <Input
              ref={barcodeRef}
              type="text"
              aria-label={t(
                nextLine ? "picking.scan_prompt" : "picking.destination_prompt",
              )}
              placeholder={t(
                nextLine ? "picking.scan_prompt" : "picking.destination_prompt",
              )}
              className="w-full rounded-xl border border-border bg-surface-card px-3 py-2 text-sm placeholder:text-on-muted focus:outline-none focus:ring-2 focus:ring-primary-500"
              onKeyDown={(e) => {
                if (e.key === "Enter") submitScan();
              }}
              data-scanner-input=""
              data-scanner-whole=""
              autoFocus
            />
          }
          refusal={refusal ?? null}
          lotRef={lotRef}
          quantity={quantity}
          onQuantityChange={setQuantity}
          onScan={submitScan}
          camera={camera}
          cameraOpen={cameraOpen}
          onCloseCamera={closeCamera}
        />
      )}

      {error && (
        <div className="px-4 py-2 bg-red-50 text-sm text-red-600 shrink-0">
          {error}
        </div>
      )}

      <div className="flex-1 overflow-y-auto">
        {/* Skipped lines stay: hidden, they could not be taken back. */}
        {lines.map((ln) => (
          <WmsPickLineRow
            key={ln.id}
            line={ln}
            showDocument={isMultiDocument}
            shelfState={shelfConfirmationState(
              session,
              ln.location_code ? ln.location_id : null,
            )}
            onFullPick={onFullPick}
            onUndo={onUndoLine}
            onShortPick={onShortPick}
            onSkip={onSkipLine}
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
              t("picking.cancel")
            )}
          </Button>
          <Button
            onClick={onComplete}
            // only unresolved lines block finishing. Requiring at least
            // one received/picked line left a session where everything was
            // skipped with no way out but Cancel — which means something else.
            disabled={
              isLoading || pendingLines.length > 0 || awaitingDestination
            }
            className="gap-1"
          >
            {isLoading ? (
              <Loader2 size={14} className="animate-spin" />
            ) : (
              <>
                <CheckCircle2 size={14} />
                {t("picking.complete")}
              </>
            )}
          </Button>
        </SheetActions>
      </SheetFooter>

      <ConfirmDialog
        open={discardAsk}
        variant="danger"
        title={t("picking.discard_confirm_title")}
        message={t("picking.discard_confirm_message")}
        confirmLabel={t("picking.cancel")}
        onConfirm={() => {
          setDiscardAsk(false);
          onCancel();
        }}
        onCancel={() => setDiscardAsk(false)}
      />
    </Sheet>
  );
}
