import type { ReactNode } from "react";
import type { UseQueryResult } from "@tanstack/react-query";
import { AlertTriangle, Lock, RefreshCw } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Button } from "./Button";
import { cn } from "@/lib/utils";
import { isForbiddenError, isUnreachableError } from "@/lib/errors";
import LoadingSpinner from "../LoadingSpinner";

interface QueryErrorProps {
  onRetry?: () => void;
  message?: string;
}

/**
 * The shared "we could not ask" state.
 *
 * `role="alert"` because it replaces content that was expected to appear: a
 * screen reader that is not told has no way to notice the message arrived and
 * left again, and none of the error states in the inventory announced anything.
 */
export function QueryError({ onRetry, message }: QueryErrorProps) {
  const { t } = useTranslation("common");
  return (
    <div
      role="alert"
      className="flex flex-col items-center justify-center gap-4 p-8 text-center"
    >
      <AlertTriangle className="w-10 h-10 text-red-400" />
      <p className="text-sm font-medium text-on-secondary">
        {message ?? t("messages.error")}
      </p>
      {onRetry && (
        <Button type="button" variant="outline" size="sm" onClick={onRetry}>
          <RefreshCw className="w-4 h-4 mr-2" />
          {t("actions.retry")}
        </Button>
      )}
    </div>
  );
}

interface QueryFailureProps {
  /** The rejected query's error, so the state can read its status. */
  error: unknown;
  onRetry?: () => void;
  message?: string;
}

/**
 * The failure state that knows "we could not" from "you may not".
 *
 * A list that renders both as its empty state tells the reader nothing is
 * there; a list that renders both as a retry offers a button that, on a
 * refusal, will never work. Neither answer is one the reader can act on.
 * `QueryFailure` reads the status and says which of the two happened, and
 * withholds the retry where retrying is pointless.
 */
export function QueryFailure({ error, onRetry, message }: QueryFailureProps) {
  const { t } = useTranslation("common");

  if (isForbiddenError(error)) {
    return (
      <div
        role="alert"
        className="flex flex-col items-center justify-center gap-3 p-8 text-center"
      >
        <Lock className="w-10 h-10 text-on-muted" aria-hidden="true" />
        <p className="text-sm font-medium text-on">{t("access.denied")}</p>
        <p className="text-sm text-on-secondary max-w-md">
          {t("access.deniedHint")}
        </p>
      </div>
    );
  }

  return <QueryError onRetry={onRetry} message={message} />;
}

interface InlineQueryErrorProps {
  /** The rejected query's error, so a refusal is not offered a retry. */
  error: unknown;
  onRetry?: () => void;
  message?: string;
  className?: string;
}

/**
 * The one-line "we could not ask" for a picker, a name lookup or a flag.
 *
 * A select whose options come from a query renders an empty list when the
 * request failed, which reads as "there is nothing to pick". This takes the
 * place of the control (or sits beside it) and says what happened, with the
 * retry where retrying can help.
 */
export function InlineQueryError({
  error,
  onRetry,
  message,
  className,
}: InlineQueryErrorProps) {
  const { t } = useTranslation("common");
  const forbidden = isForbiddenError(error);
  return (
    <div
      role="alert"
      className={cn(
        "flex flex-wrap items-center gap-2 text-sm text-red-600",
        className,
      )}
    >
      <AlertTriangle className="h-4 w-4 shrink-0" aria-hidden="true" />
      <span>
        {forbidden
          ? t("access.denied")
          : (message ??
            (isUnreachableError(error)
              ? t("errors.backendUnavailableTitle")
              : t("messages.error")))}
      </span>
      {onRetry && !forbidden && (
        <Button type="button" variant="ghost" size="sm" onClick={onRetry}>
          <RefreshCw className="mr-1 h-3.5 w-3.5" aria-hidden="true" />
          {t("actions.retry")}
        </Button>
      )}
    </div>
  );
}

interface QueryResultProps<T> {
  query: UseQueryResult<T>;
  children: (data: NonNullable<T>) => ReactNode;
  loadingFallback?: ReactNode;
  errorFallback?: ReactNode;
  /** Render even when data is null/undefined (children receives T, caller handles null) */
  renderWhenEmpty?: boolean;
}

export function QueryResult<T>({
  query,
  children,
  loadingFallback,
  errorFallback,
  renderWhenEmpty = false,
}: QueryResultProps<T>) {
  if (query.isLoading) {
    return <>{loadingFallback ?? <LoadingSpinner />}</>;
  }
  if (query.isError) {
    return (
      <>{errorFallback ?? <QueryError onRetry={() => query.refetch()} />}</>
    );
  }
  if (!renderWhenEmpty && (query.data === null || query.data === undefined)) {
    return null;
  }
  return <>{children(query.data as NonNullable<T>)}</>;
}
