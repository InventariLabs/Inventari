import type { ReactNode } from "react";
import { AlertTriangle, Lock } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/Button";
import { isForbiddenError } from "@/lib/errors";

/**
 * Stands in for the "at home" toggle when the exclusions did not load. The
 * toggle's state comes from that list: without it every ingredient reads as
 * "not excluded", and a press would add an exclusion that is already there or
 * fail to remove one. Takes the toggle as `children` so the caller keeps its
 * own branches out of the way of a failed read.
 */
export function ExclusionGate({
  failed,
  error,
  onRetry,
  children,
}: {
  failed: boolean;
  /** The rejected read's error: a refusal shows no retry, it would repeat. */
  error: unknown;
  onRetry: () => void;
  children: ReactNode;
}) {
  const { t } = useTranslation("common");
  if (!failed) return <>{children}</>;
  if (isForbiddenError(error)) {
    return (
      <span
        role="img"
        className="inline-flex shrink-0 text-on-muted"
        aria-label={t("access.denied")}
        title={t("access.denied")}
      >
        <Lock size={16} aria-hidden="true" />
      </span>
    );
  }
  return (
    <Button
      type="button"
      variant="ghost"
      size="iconSm"
      onClick={onRetry}
      className="shrink-0 rounded text-on-danger"
      aria-label={t("actions.retry")}
      title={t("messages.error")}
    >
      <AlertTriangle size={16} />
    </Button>
  );
}
