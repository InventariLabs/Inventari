import { useEffect, useRef } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { PACKING_HASH } from "@/modules/warehouse/components/packing/DocumentPackingStep";
import type { ShipmentCreate } from "@/modules/warehouse/api/shipments";
import type { ShipmentDraft } from "@/modules/warehouse/components/shipping/shipmentDraft";
import type { WarehouseDocument } from "@/modules/warehouse/types";

/** What a list's picking sheet leaves for the document's page to finish. */
interface HandedOver {
  completeAfterPicking?: { shipment?: ShipmentCreate };
}

/**
 * How a list ends a picking sheet that covered one document.
 *
 * Completing a dispatch and packing it are its own page's work: the page asks
 * the questions a completion can stop on (a record kept in another unit),
 * carries the Undo and the backorder link the answer brings, and holds the
 * Pack step. A list has none of that, so a one-document session started from
 * one — a single ticked row, a selection the stock check narrowed to one, or
 * Resume — hands the document to its page: Pack lands on the Pack step, and
 * Complete and book on the page completing it with the carrier the summary
 * took. A session over several documents leaves each picked and open, and the
 * list stays where it is.
 */
export function usePickingHandOff(onLeave: () => void) {
  const navigate = useNavigate();
  return {
    onClose: (
      completed?: boolean,
      shipment?: ShipmentCreate,
      documentId?: string,
    ) => {
      onLeave();
      if (!completed || !documentId) return;
      const state: HandedOver = { completeAfterPicking: { shipment } };
      navigate(`/warehouse/documents/${documentId}`, { state });
    },
    onPack: (shipment: ShipmentDraft, documentId: string) => {
      onLeave();
      navigate(`/warehouse/documents/${documentId}${PACKING_HASH}`, {
        state: { shipment },
      });
    },
  };
}

/**
 * The document page's half: completes what a list's picking sheet handed
 * over, once the document has loaded, and spends the hand-off so that a
 * reload or Back does not complete it again. A document no longer confirmed
 * — completed or cancelled meanwhile — is left as it is.
 */
export function useHandedOverCompletion(
  doc: WarehouseDocument | undefined,
  complete: (shipment?: ShipmentCreate) => void,
) {
  const location = useLocation();
  const navigate = useNavigate();
  const handed = (location.state as HandedOver | null)?.completeAfterPicking;
  const taken = useRef(false);
  useEffect(() => {
    if (!handed || !doc || taken.current) return;
    taken.current = true;
    navigate(location, { replace: true, state: null });
    if (doc.status === "CONFIRMED") complete(handed.shipment);
  }, [handed, doc, complete, navigate, location]);
}
