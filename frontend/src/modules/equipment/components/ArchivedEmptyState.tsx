import { useTranslation } from "react-i18next";
import { Card } from "@/components/ui/Card";

interface ArchivedEmptyStateProps {
  /** The phrase in the toolbar's box — the active and archived tabs share it. */
  search: string;
}

/**
 * The archived tab's empty panel, told apart from a phrase that matched
 * nothing. The same box narrows both tabs, and "retired assets will appear
 * here" under a phrase that simply missed reads as if the search had not
 * worked.
 */
export function ArchivedEmptyState({ search }: ArchivedEmptyStateProps) {
  const { t } = useTranslation("equipment");
  return (
    <Card className="p-8 text-center">
      <p className="text-sm font-medium text-on mb-1">
        {search ? t("list.no_results") : t("list.no_archived")}
      </p>
      {!search && (
        <p className="text-xs text-on-muted">{t("list.no_archived_hint")}</p>
      )}
    </Card>
  );
}
