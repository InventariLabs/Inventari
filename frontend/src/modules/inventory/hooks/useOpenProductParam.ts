import { useCallback, useRef, useState } from "react";
import { useLocation, useNavigate, useSearchParams } from "react-router-dom";
import { hasHistoryToPop } from "@/module-sdk";

/**
 * The product dialog of the list, kept in the address as `?open=<id>`.
 *
 * A dialog that came with the address — a row of the overview links here with
 * `?open=` — is closed by going back to where the link was, not by landing on
 * this list. Not when the address was typed or bookmarked (no earlier entry in the
 * history): there is nothing to go back to, so it closes
 * in place.
 *
 * `&at=expiry` opens the dialog at the expiry date. It belongs to the link that
 * carried it: the next product opened from the list starts at the top.
 */
export function useOpenProductParam(): [
  string | null,
  (id: string | null) => void,
] {
  const navigate = useNavigate();
  const location = useLocation();
  const [searchParams, setSearchParams] = useSearchParams();
  const [openId, setOpenId] = useState<string | null>(() =>
    searchParams.get("open"),
  );
  const openedByLink = useRef(
    searchParams.get("open") !== null && hasHistoryToPop(location),
  );

  const setOpen = useCallback(
    (id: string | null) => {
      const closingLinkedDialog = id === null && openedByLink.current;
      openedByLink.current = false;
      if (closingLinkedDialog) {
        navigate(-1);
        return;
      }
      setOpenId(id);
      const next = new URLSearchParams(searchParams);
      next.delete("at");
      if (id) next.set("open", id);
      else next.delete("open");
      setSearchParams(next, { replace: true });
    },
    [navigate, searchParams, setSearchParams],
  );

  return [openId, setOpen];
}
