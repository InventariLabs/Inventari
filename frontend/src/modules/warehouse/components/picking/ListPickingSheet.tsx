import WmsPickingView from "@/modules/warehouse/components/picking/WmsPickingView";
import { usePickingHandOff } from "@/modules/warehouse/hooks/usePickingHandOff";

interface Props {
  /** The dispatches ticked, or the one row resumed; fixed when it opens. */
  documentIds: string[];
  /** The sheet is gone: the list clears what opened it. */
  onLeave: () => void;
  /** Every dispatch opened is internal, so no screen of it asks for a carrier. */
  withoutCarrier?: boolean;
}

/**
 * The picking sheet a list opens. A session that ends over one document
 * hands it to that document's page to be packed or completed; one over
 * several leaves each picked and open (`usePickingHandOff`).
 */
export function ListPickingSheet({
  documentIds,
  onLeave,
  withoutCarrier,
}: Props) {
  const handOff = usePickingHandOff(onLeave);
  return (
    <WmsPickingView
      documentId={documentIds[0]}
      documentIds={documentIds}
      onClose={handOff.onClose}
      onPack={handOff.onPack}
      withoutCarrier={withoutCarrier}
    />
  );
}
