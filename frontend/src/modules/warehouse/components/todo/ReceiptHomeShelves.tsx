import { useEffect, useRef, useState } from "react";
import { useMediaQuery } from "@/hooks/useMediaQuery";
import type { HomeShelfOffer } from "@/modules/warehouse/api/putaway";
import { useReceiptHomeShelfOffers } from "@/modules/warehouse/hooks/usePutawayRules";
import { HomeShelvesSheet } from "./HomeShelvesSheet";

const PHONE_QUERY = "(max-width: 639px)";

/**
 * The home-shelf question of a receipt that has just been posted: nothing on
 * the screen while there is nothing to ask, the one sheet when there is. The
 * server decides what is asked; a receipt in two steps, a warehouse without
 * fixed places and a silenced product ask nothing here.
 *
 * The questions are taken once, as the posted receipt gave them: an answer
 * refreshes the read, and the rows still waiting must not vanish with it.
 */
export function ReceiptHomeShelves({ documentId }: { documentId: string }) {
  const { data } = useReceiptHomeShelfOffers(documentId);
  const isPhone = useMediaQuery(PHONE_QUERY);
  const [asked, setAsked] = useState<HomeShelfOffer[] | null>(null);
  const [dismissed, setDismissed] = useState(false);
  if (asked === null && data !== undefined) setAsked(data);
  if (dismissed || !asked || asked.length === 0) return null;
  return (
    <HomeShelvesSheet
      offers={asked}
      isPhone={isPhone}
      onDone={() => setDismissed(true)}
    />
  );
}

/**
 * The same question for a receipt posted from its own page — the scan
 * session, "post now", "complete": it is asked when the page watches the
 * receipt turn completed, never for one that was already completed when the
 * page opened.
 */
export function HomeShelvesAfterPosting({
  documentId,
  status,
}: {
  documentId: string;
  status: string;
}) {
  const before = useRef(status);
  const [posted, setPosted] = useState(false);
  useEffect(() => {
    if (before.current !== "COMPLETED" && status === "COMPLETED")
      setPosted(true);
    before.current = status;
  }, [status]);
  return posted ? <ReceiptHomeShelves documentId={documentId} /> : null;
}
