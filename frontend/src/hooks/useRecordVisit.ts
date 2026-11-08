import { useEffect } from "react";
import { useLocation } from "react-router-dom";
import { addRecentItem, RECENT_ITEMS_SCOPE } from "@/lib/recentItems";
import { useAuthStore } from "@/store/authStore";

/** The record a page shows, as "Recently visited" names it. */
export interface VisitedRecord {
  /** A second visit moves the record to the top instead of adding it again. */
  id: string;
  name: string;
}

/**
 * Puts the record a page shows at the top of the signed-in person's
 * "Recently visited" — the launcher's panel and the command palette's recent
 * list — under the page's own address. A page calls it with its record once
 * it has loaded, and with nothing before; a renamed record is stored under
 * its new name. `module` is the page's module, which the list names the way
 * its tile does.
 *
 * Only the record pages a person comes back to call it — a product, an asset,
 * a recipe. A module that has such a page records its visits the same way.
 */
export function useRecordVisit(
  module: string,
  record: VisitedRecord | null | undefined,
): void {
  const userId = useAuthStore((s) => s.user?.id);
  const { pathname } = useLocation();
  const id = record?.id;
  const title = record?.name;
  useEffect(() => {
    if (userId == null || !id || !title) return;
    addRecentItem(
      { id, title, module, path: pathname, timestamp: Date.now() },
      String(userId),
      RECENT_ITEMS_SCOPE,
    );
  }, [userId, id, title, module, pathname]);
}
