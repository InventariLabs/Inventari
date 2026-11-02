import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/Button";

/**
 * What a location picker's panel says when its search failed.
 *
 * A search that failed says nothing about whether there are places, so the
 * panel says it failed and offers a retry — never "no results".
 */
export function LocationSearchFailed({ onRetry }: { onRetry: () => void }) {
  const { t } = useTranslation();
  return (
    <span role="alert" className="inline-flex items-center gap-2">
      {t("common:messages.error")}
      <Button type="button" variant="ghost" size="sm" onClick={onRetry}>
        {t("common:actions.retry")}
      </Button>
    </span>
  );
}
