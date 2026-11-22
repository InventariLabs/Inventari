import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/Button";
import { isForbiddenError } from "@/lib/errors";

/**
 * What a location picker's panel says when its search failed.
 *
 * A search that failed says nothing about whether there are places, so the
 * panel says it failed and offers a retry — never "no results". A refusal
 * (403) says so instead and offers none: asking again is refused again.
 */
export function LocationSearchFailed({
  error,
  onRetry,
}: {
  /** The rejected search's error. */
  error: unknown;
  onRetry: () => void;
}) {
  const { t } = useTranslation();
  const forbidden = isForbiddenError(error);
  return (
    <span role="alert" className="inline-flex items-center gap-2">
      {forbidden ? t("common:access.denied") : t("common:messages.error")}
      {!forbidden && (
        <Button type="button" variant="ghost" size="sm" onClick={onRetry}>
          {t("common:actions.retry")}
        </Button>
      )}
    </span>
  );
}
