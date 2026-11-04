import { useEffect, useState } from "react";
import { useLocation } from "react-router-dom";
import { useTranslation } from "react-i18next";
import i18next from "i18next";
import { CheckCircle2, FileText } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { runWithToast } from "@/lib/api/runWithToast";
import { downloadBlob } from "@/utils/helpers";
import { packingApi } from "@/modules/warehouse/api/packing";
import type { ShipmentCreate } from "@/modules/warehouse/api/shipments";
import type { WarehouseDocument } from "@/modules/warehouse/types";
import { ShipmentFields } from "../shipping/ShipmentFields";
import {
  EMPTY_SHIPMENT,
  type ShipmentDraft,
  shipmentError,
  shipmentPayload,
} from "../shipping/shipmentDraft";

interface Props {
  document: WarehouseDocument;
  packageCount: number;
  /** The reader may complete the dispatch from here. */
  canComplete: boolean;
  /** Goods still wait to be packed. */
  packingLeft: boolean;
  isCompletePending: boolean;
  isWritePending: boolean;
  onComplete: (shipment?: ShipmentCreate) => void;
}

/** Every package's slip in one file, the carrier they leave with, and the
 * completion that ships them. */
export function PackingFooter({
  document,
  packageCount,
  canComplete,
  packingLeft,
  isCompletePending,
  isWritePending,
  onComplete,
}: Props) {
  const { t } = useTranslation("warehouse");
  const [slipPending, setSlipPending] = useState(false);
  // The picking summary hands over the carrier it already asked for.
  const carried = (useLocation().state as { shipment?: ShipmentDraft } | null)
    ?.shipment;
  const [shipment, setShipment] = useState(carried ?? EMPTY_SHIPMENT);
  const [shipmentFault, setShipmentFault] = useState<string>();
  // The step can already be on the page when the summary hands the carrier over.
  useEffect(() => {
    if (carried) setShipment(carried);
  }, [carried]);

  if (packageCount < 2 && !canComplete) return null;

  const downloadAllSlips = async () => {
    setSlipPending(true);
    await runWithToast(
      async () => {
        const blob = await packingApi.slipPdf(
          document.id,
          null,
          i18next.language || "en",
        );
        downloadBlob(
          blob,
          `packing_slip_${document.number.replace(/[/\s]/g, "-")}.pdf`,
        );
      },
      { errorFallback: t("packing.errors.slipFailed") },
    );
    setSlipPending(false);
  };

  const complete = () => {
    const fault = shipmentError(shipment, t);
    setShipmentFault(fault);
    if (!fault) onComplete(shipmentPayload(shipment));
  };

  return (
    <div className="space-y-4 border-t border-border pt-4">
      {canComplete && (
        <ShipmentFields
          value={shipment}
          onChange={setShipment}
          error={shipmentFault}
        />
      )}
      <div className="flex flex-wrap items-center justify-end gap-2">
        {/* One package's slip is on its own card; the file of all of them
          earns a button once there is more than one. */}
        {packageCount > 1 && (
          <Button
            variant="outline"
            leftIcon={<FileText size={16} />}
            isLoading={slipPending}
            onClick={() => void downloadAllSlips()}
          >
            {t("packing.slipAll")}
          </Button>
        )}
        {canComplete && (
          <Button
            // One filled button per screen: while goods wait to be packed
            // the packing action is the next step, and completing without
            // packing stays a step away, not a rival.
            variant={packingLeft ? "outline" : "default"}
            leftIcon={<CheckCircle2 size={16} />}
            isLoading={isCompletePending}
            disabled={isWritePending}
            onClick={complete}
          >
            {t("packing.complete")}
          </Button>
        )}
      </div>
    </div>
  );
}
