import { useCallback, useState } from "react";
import type { Partner, PartnerType } from "@/types";

/**
 * The inline partner-create layer's plumbing: open/query state and the
 * handlers the host form wires to it.
 *
 * `handleCreated` refuses a partner of a role the host field does not list —
 * such a partner would sit beneath the placeholder looking empty while the
 * form read the field as filled. The layer stays open: its type select is
 * the way to a role that fits.
 */
export function usePartnerCreateLayer({
  roleTypes,
  onAccepted,
}: {
  roleTypes: readonly PartnerType[];
  onAccepted: (partnerId: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");

  const handleCreate = useCallback((nextQuery: string) => {
    setQuery(nextQuery);
    setOpen(true);
  }, []);

  const handleCreated = useCallback(
    (partner: Partner) => {
      if (!roleTypes.includes(partner.type as PartnerType)) return;
      onAccepted(partner.id);
      setOpen(false);
      setQuery("");
    },
    [roleTypes, onAccepted],
  );

  const handleCancel = useCallback(() => {
    setOpen(false);
    setQuery("");
  }, []);

  return { open, query, handleCreate, handleCreated, handleCancel };
}
