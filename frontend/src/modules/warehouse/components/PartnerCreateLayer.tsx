import {
  PartnerInlineCreate,
  usePartnerCreateLayer,
} from "@/modules/partners/moduleApi";
import type { PartnerType } from "@/types";

/**
 * The form a partner field of the goods screens opens for a partner who does
 * not exist yet. Its own file so that those screens can load it when asked:
 * a worker on a phone rarely opens it, and pays for each screen's JavaScript.
 */
export default function PartnerCreateLayer({
  initialName,
  roleTypes,
  onAccepted,
  onClose,
  returnFocusId,
}: {
  initialName: string;
  roleTypes: readonly PartnerType[];
  onAccepted: (partnerId: string) => void;
  onClose: () => void;
  /** The partner field that opened the layer — it gets the focus back. */
  returnFocusId?: string;
}) {
  const { handleCreated } = usePartnerCreateLayer({
    roleTypes,
    onAccepted: (partnerId) => {
      onAccepted(partnerId);
      onClose();
    },
  });
  return (
    <div className="col-span-full">
      <PartnerInlineCreate
        initialName={initialName}
        roleTypes={roleTypes}
        onCreated={handleCreated}
        onCancel={onClose}
        returnFocusId={returnFocusId}
      />
    </div>
  );
}
