import type { Dispatch, SetStateAction } from "react";
import { useTranslation } from "react-i18next";
import { Checkbox } from "@/components/ui/Checkbox";
import type { LabelPool } from "@/types";

/**
 * The table header's checkbox. It selects or clears the labels on this page
 * only: a selection made on another page stays as it was.
 */
export function LabelPageSelectAll({
  labels,
  selectedIds,
  setSelectedIds,
}: {
  labels: LabelPool[];
  selectedIds: string[];
  setSelectedIds: Dispatch<SetStateAction<string[]>>;
}) {
  const { t } = useTranslation("common");
  const onPage = labels.filter((l) => selectedIds.includes(l.id)).length;
  const allOnPage = labels.length > 0 && onPage === labels.length;
  const pageIds = labels.map((l) => l.id);
  return (
    <Checkbox
      touchTarget
      checked={allOnPage}
      indeterminate={onPage > 0 && !allOnPage}
      onChange={() =>
        setSelectedIds((prev) =>
          allOnPage
            ? prev.filter((id) => !pageIds.includes(id))
            : [...prev, ...pageIds.filter((id) => !prev.includes(id))],
        )
      }
      className="w-4 h-4 accent-primary-500"
      aria-label={t("actions.selectAll")}
    />
  );
}
