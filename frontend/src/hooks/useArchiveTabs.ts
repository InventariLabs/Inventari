import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import type { ListControlBarPrimaryTabsProps } from "@/components/ui/ListControlBar";

export type ArchiveTab = "active" | "archived";

/**
 * The tab pair that makes a list and its archive one list in two states.
 *
 * Archiving is the industry-standard way to retire a record documents and
 * history still point at; a menu entry per archive is not — every comparable
 * system offers the archive as a state of the list it belongs to. Here the two
 * states live on two routes, because the active list carries filters,
 * selection and bulk actions the archive has no use for. Switching is left to
 * the caller so the route it navigates to is written where a reader (and the
 * reachability gate) looks for it: in the page that leads there.
 */
export function useArchiveTabs(
  showing: ArchiveTab,
  onSwitch: (tab: ArchiveTab) => void,
): ListControlBarPrimaryTabsProps {
  const { t } = useTranslation("common");

  return useMemo(
    () => ({
      value: showing,
      onChange: (value: string) => onSwitch(value as ArchiveTab),
      options: [
        { value: "active", label: t("archiveTabs.active") },
        { value: "archived", label: t("archiveTabs.archived") },
      ],
    }),
    [showing, onSwitch, t],
  );
}
