import { createPortal } from "react-dom";
import { useProductLabelRequest } from "@/modules/printing/hooks/useProductLabelRequest";
import { BarcodeLabelSheet } from "@/modules/shared/components/BarcodeLabelSheet";

/**
 * The product label sheet, wherever a bulk action asked for it.
 *
 * Portalled to the body: the slot it is mounted in is the shell's sticky
 * notice strip, whose own stacking layer would otherwise hold the sheet
 * under the top bar and the list's selection toolbar.
 */
export default function ProductLabelSheetHost() {
  const itemIds = useProductLabelRequest((s) => s.itemIds);
  const close = useProductLabelRequest((s) => s.close);
  if (!itemIds || itemIds.length === 0) return null;
  return createPortal(
    <BarcodeLabelSheet target={{ itemIds }} onClose={close} />,
    document.body,
  );
}
