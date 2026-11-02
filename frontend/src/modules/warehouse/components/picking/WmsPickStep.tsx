import type { ReactNode, Ref } from "react";
import { useTranslation } from "react-i18next";
import { MapPin, ScanLine } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { QuantityInput } from "@/components/ui/QuantityInput";
import { ScanCameraPanel } from "@/components/ui/ScanCameraPanel";
import { ScannerReadyHint } from "@/components/ui/ScannerReadyHint";
import { useScanCamera } from "@/hooks/useScanCamera";
import { useMediaQuery } from "@/hooks/useMediaQuery";
import type {
  WmsPickLine,
  WmsPickSession,
} from "@/modules/warehouse/api/documents";
import { formatQuantityValue } from "@/utils/formatters";
import { unitLabel } from "@/lib/i18nHelpers";
import FloorShelf, { type FloorShelfPlace } from "../FloorShelf";
import { shelfConfirmationState } from "../ShelfConfirmation";
import ScanRefusal from "../ScanRefusal";

/** Below `sm` the walk leads with the shelf, as a phone holds it. */
const PHONE_QUERY = "(max-width: 639px)";

/** The shelf this step leads to: the line's own, or a transfer's destination. */
function shelfFor(
  session: WmsPickSession,
  line: WmsPickLine | null,
  awaitingDestination: boolean,
): FloorShelfPlace | null {
  if (awaitingDestination) {
    return session.destination_shelf
      ? {
          code: session.destination_shelf_code ?? null,
          name: session.destination_shelf,
        }
      : null;
  }
  if (!line || !(line.location_name || line.bin_location)) return null;
  return {
    code: line.location_code ?? null,
    name: line.location_name ?? line.bin_location ?? "",
  };
}

/** The product in hand, and how much of it this step still expects. */
function PickProductLine({
  line,
  showDocument,
}: {
  line: WmsPickLine;
  showDocument: boolean;
}) {
  const { t } = useTranslation("warehouse");
  // a line part of which is already picked stays the next one to scan, so
  // naming only what was planned would put "4" above a field whose job is
  // now to take the remaining 2.
  return (
    <p className="text-sm text-on-secondary">
      {showDocument && line.document_number && (
        <span className="font-medium text-on">{line.document_number} · </span>
      )}
      {line.product_name} —{" "}
      {line.picked_quantity > 0
        ? `${formatQuantityValue(line.picked_quantity)}/${formatQuantityValue(line.expected_quantity)}`
        : formatQuantityValue(line.expected_quantity)}{" "}
      {unitLabel(t, line.uom_symbol)}
      {/* The batch the scan enforces: the picker reads it off the label. */}
      {line.lot_name && (
        <span className="font-medium text-on">
          {" · "}
          {t("picking.lot", { name: line.lot_name })}
        </span>
      )}
    </p>
  );
}

/** The desktop's small "where to walk" line: a phone reads the card instead.
 * Not in link colour: nothing here opens, and blue text invites a tap. */
function GoToLine({ children }: { children: ReactNode }) {
  return (
    <p className="mt-1.5 text-xs text-on-secondary font-medium flex items-center gap-1">
      <MapPin size={12} />
      {children}
    </p>
  );
}

interface Props {
  session: WmsPickSession;
  /** The line in hand: the first still pending. */
  line: WmsPickLine | null;
  /** Every line answered on a transfer: its destination label is the step. */
  awaitingDestination: boolean;
  /** One session over several dispatches: each line names its document. */
  showDocument: boolean;
  /** The barcode field, rendered here but owned by the screen that scans it. */
  scanField: ReactNode;
  /** The last refused scan, said beside the field until the next one. */
  refusal: string | null;
  lotRef: Ref<HTMLInputElement>;
  quantity: string;
  onQuantityChange: (value: string) => void;
  /** One code, whether typed, scanned by hardware or read by the camera. */
  onScan: () => void;
  camera: ReturnType<typeof useScanCamera>;
  cameraOpen: boolean;
  onCloseCamera: () => void;
}

/**
 * The step in hand, above the session's lines: on a phone the shelf the
 * worker walks to — its code large, the name under it, and whether its label
 * still has to be scanned — and then the product to scan there. On a desktop
 * the same block names the shelf in the smaller line the wide screen reads
 * beside the rest of the session.
 */
export default function WmsPickStep({
  session,
  line,
  awaitingDestination,
  showDocument,
  scanField,
  refusal,
  lotRef,
  quantity,
  onQuantityChange,
  onScan,
  camera,
  cameraOpen,
  onCloseCamera,
}: Props) {
  const { t } = useTranslation(["warehouse", "common"]);
  const isPhone = useMediaQuery(PHONE_QUERY);
  const shelf = shelfFor(session, line, awaitingDestination);

  return (
    <div className="px-4 py-2 bg-surface border-b border-border shrink-0">
      {/* the barcode field is the point of the screen — full
          width row; quantity + scan action move to a second line. */}
      <div className="flex flex-col gap-2">
        {isPhone && (
          <FloorShelf
            label={
              awaitingDestination
                ? t("picking.floorShelf.takeTo")
                : t("picking.floorShelf.takeFrom")
            }
            shelf={shelf}
            confirmation={
              awaitingDestination
                ? "toScan"
                : line
                  ? shelfConfirmationState(
                      session,
                      line.location_code ? line.location_id : null,
                    )
                  : null
            }
            kind="picking"
          />
        )}
        {line && <PickProductLine line={line} showDocument={showDocument} />}
        {scanField}
        {refusal && <ScanRefusal message={refusal} />}
        {line && (
          // The batch code on the label, when the picker reads one: the
          // server checks it against the batch the row names.
          <Input
            ref={lotRef}
            type="text"
            aria-label={t("picking.lot_prompt")}
            placeholder={t("picking.lot_prompt")}
            className="w-full rounded-xl border border-border bg-surface-card px-3 py-2 text-sm placeholder:text-on-muted focus:outline-none focus:ring-2 focus:ring-primary-500"
            onKeyDown={(e) => {
              if (e.key === "Enter") onScan();
            }}
          />
        )}
        <div className="flex items-center gap-2">
          {line && (
            // The unit decides the step, not this screen. It used to be
            // hardcoded, and the four quantity fields of this module
            // between them carried four different answers.
            <QuantityInput
              wrapperClassName="w-24"
              uomSymbol={line.uom_symbol ?? undefined}
              value={quantity}
              onChange={(e) => onQuantityChange(e.target.value)}
              className="rounded-xl border border-border bg-surface-card px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary-500"
              aria-label={t("picking.quantity")}
              // A scan taken while this field has the focus is still the
              // barcode's; what was typed here stays.
              data-scanner-keep=""
            />
          )}
          <Button
            type="button"
            variant="default"
            size="sm"
            className="flex-1 rounded-xl shadow-none"
            onClick={() => onScan()}
          >
            <ScanLine size={16} />
            <span>{t("picking.scanAction")}</span>
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
        onClose={onCloseCamera}
        className="mt-2"
      />

      {!isPhone && awaitingDestination && (
        <GoToLine>
          {t("picking.destination_go_to", {
            location: session.destination_shelf,
          })}
        </GoToLine>
      )}
      {!isPhone && line?.bin_location && (
        <GoToLine>
          {t("picking.go_to", { location: line.bin_location })}
        </GoToLine>
      )}
    </div>
  );
}
