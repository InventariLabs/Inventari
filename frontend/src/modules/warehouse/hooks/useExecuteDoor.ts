import { useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { usePackingStepShown } from "@/modules/warehouse/components/packing/DocumentPackingStep";
import { PACKING_HASH } from "@/modules/warehouse/components/packing/packingHash";
import type { WarehouseDocument } from "@/modules/warehouse/types";

/**
 * How a confirmed document gets completed from its page.
 *
 * A picked dispatch is completed in the Pack step, which carries the carrier
 * and the tracking number, so the page keeps one door: the header's Execute
 * leads there and the execution panel stays closed. While a picking session is
 * still open over it the step is not on the page, and every other document has
 * none: those open the execution panel.
 */
export function useExecuteDoor(
  doc: WarehouseDocument | undefined,
  executionOpen: boolean,
  setExecutionOpen: (open: boolean) => void,
) {
  const navigate = useNavigate();
  const packed = usePackingStepShown(doc);
  const execute = useCallback(() => {
    if (packed) navigate({ hash: PACKING_HASH }, { replace: true });
    else setExecutionOpen(true);
  }, [packed, navigate, setExecutionOpen]);
  // The panel never opens beside the Pack step it would duplicate.
  return { execute, panelOpen: executionOpen && !packed };
}
