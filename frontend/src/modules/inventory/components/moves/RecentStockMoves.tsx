/**
 * The movement ledger, asked one subject's question.
 *
 * The full ledger screen answers "what moved"; this panel answers "what
 * moved *here*" or "what moved *this*", and it is the same rows, the same
 * table and the same paging — a second component would be a second answer
 * to maintain.
 *
 * It pages rather than truncating: a product with forty movements has
 * forty movements, and a list that silently stops at ten teaches the reader
 * to distrust it. The link out is for the wider question (this product
 * everywhere), not for the rest of this one.
 */
import { Link } from "react-router-dom";
import { ArrowLeftRight, ArrowUpRight } from "lucide-react";
import { EmptyState } from "@/components/ui/EmptyState";
import { Pagination } from "@/module-sdk";
import LoadingSpinner from "@/components/LoadingSpinner";
import { QueryFailure } from "@/components/ui/QueryResult";
import { useStockMoves } from "../../hooks/useStockMoves";
import { StockMovesTable } from "../StockMovesTable";
import { StockMoveCards } from "../StockMoveCards";
import { useKeysetPaging } from "@/hooks/useKeysetPaging";
import type { StockMoveFilters } from "@/lib/api/stockMoves";
import { pageTotal } from "../../utils/pageTotal";

const PAGE_SIZE = 20;

interface RecentStockMovesProps {
  /** The subject: which product, which place, which batch. */
  filters: Omit<StockMoveFilters, "limit" | "cursor">;
  /** What this list is, in one sentence, above the rows. */
  caption: string;
  /** Where the wider version of this question lives, and what to call it. */
  seeAll?: { to: string; label: string };
  /** False on a product's own card, where every row names the same product. */
  showProduct?: boolean;
  emptyTitle: string;
  emptyDescription: string;
}

export function RecentStockMoves({
  filters,
  caption,
  seeAll,
  showProduct = true,
  emptyTitle,
  emptyDescription,
}: RecentStockMovesProps) {
  const paging = useKeysetPaging(filters);

  const { data, isLoading, isError, error, isPlaceholderData, refetch } =
    useStockMoves({
      ...filters,
      limit: PAGE_SIZE,
      cursor: paging.cursor,
    });

  const moves = data?.items ?? [];
  // The same ledger, so the same capped count as the full screen.
  const { total, totalCapped } = pageTotal(data);

  if (isError) {
    return <QueryFailure error={error} onRetry={() => void refetch()} />;
  }
  if (isLoading) return <LoadingSpinner />;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <p className="text-sm text-on-secondary">{caption}</p>
        {seeAll && (
          <Link
            to={seeAll.to}
            className="inline-flex items-center gap-1 text-sm font-medium text-on-primary hover:underline"
          >
            {seeAll.label}
            <ArrowUpRight size={14} aria-hidden="true" />
          </Link>
        )}
      </div>

      {moves.length === 0 ? (
        <EmptyState
          icon={ArrowLeftRight}
          title={emptyTitle}
          description={emptyDescription}
        />
      ) : (
        <>
          <div className="hidden md:block">
            <StockMovesTable moves={moves} showProduct={showProduct} />
          </div>
          <div className="md:hidden">
            <StockMoveCards moves={moves} showProduct={showProduct} />
          </div>
          {total > PAGE_SIZE && (
            <Pagination
              skip={paging.page * PAGE_SIZE}
              limit={PAGE_SIZE}
              total={total}
              totalCapped={totalCapped}
              keyset={{
                rows: moves.length,
                hasNext: Boolean(data?.next_cursor),
              }}
              onPrev={paging.goPrev}
              // The cursor on screen belongs to the page it came with; while
              // the next page loads the old rows are still shown, and their
              // cursor must not be taken for the new page's.
              onNext={() =>
                !isPlaceholderData && paging.goNext(data?.next_cursor)
              }
            />
          )}
        </>
      )}
    </div>
  );
}
