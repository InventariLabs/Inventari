import { SearchX, type LucideIcon } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { Button } from "@/components/ui/Button";
import { EmptyState } from "@/components/ui/EmptyState";

/**
 * The screen a detail route shows when its record is not there.
 *
 * A 404 is an answer, not a hiccup: the server understood the request and said
 * the record is gone. The reader needs two things from that answer — a sentence
 * naming what was not found, and one way onwards — and used to get neither in
 * the same shape twice. Eleven detail screens had six different replies to the
 * same condition, from a bare sentence with no exit to a spinner that never
 * stopped, because each one wrote its own.
 *
 * Pair it with `isNotFoundError` so a failed request keeps its own branch:
 *
 *     if (isLoading) return <LoadingSpinner />;
 *     if (isError && !isNotFoundError(error)) return <QueryError onRetry={refetch} />;
 *     if (!record) return <RecordNotFound title={…} backTo="/…" backLabel={…} />;
 *
 * Retrying is deliberately not offered here — `shouldRetryQuery` already stops
 * repeating a 4xx, and a button that repeats a doomed request sends the reader
 * back to the same wall.
 */
export interface RecordNotFoundProps {
  /** Names what was not found, in the module's own noun. */
  title: string;
  description?: string;
  /** Where the one way onwards leads — normally the record's list. */
  backTo: string;
  backLabel: string;
  icon?: LucideIcon;
}

export function RecordNotFound({
  title,
  description,
  backTo,
  backLabel,
  icon = SearchX,
}: RecordNotFoundProps) {
  const navigate = useNavigate();
  return (
    <EmptyState
      icon={icon}
      title={title}
      description={description}
      primaryAction={
        <Button variant="link" onClick={() => navigate(backTo)}>
          {backLabel}
        </Button>
      }
    />
  );
}

export default RecordNotFound;
