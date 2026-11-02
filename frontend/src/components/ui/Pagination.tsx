import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { Input } from "@/components/ui/Input";
import { NativeSelect } from "@/components/ui/NativeSelect";

const DEFAULT_PAGE_SIZES = [25, 50, 100, 200];

interface PaginationProps {
  skip: number;
  limit: number;
  total: number;
  /**
   * The list stopped counting at `total` and holds more (`total_capped` on
   * the page). The bar says "of more than …", offers the pages it counted,
   * and keeps "next" open past them.
   */
  totalCapped?: boolean;
  /**
   * A cursor-paged list: the rows on this page and whether a cursor leads
   * past them. Given, the cursor decides "next", and a capped total the pages
   * have walked past gives way to the rows walked — such a list counts on its
   * first page only, so its later pages carry that first count.
   */
  keyset?: { rows: number; hasNext: boolean };
  onPrev: () => void;
  onNext: () => void;
  /**
   * Jump straight to a page (1-based). Omit and the bar keeps prev/next only —
   * thirteen pages then cost twelve clicks to cross.
   */
  onPageChange?: (page: number) => void;
  /** Change rows per page. Omit to leave the picker out. */
  onLimitChange?: (limit: number) => void;
  pageSizeOptions?: number[];
}

export default function Pagination({
  skip,
  limit,
  total: counted,
  totalCapped: countCapped = false,
  keyset,
  onPrev,
  onNext,
  onPageChange,
  onLimitChange,
  pageSizeOptions = DEFAULT_PAGE_SIZES,
}: PaginationProps) {
  const { t } = useTranslation("common");

  const page = Math.floor(skip / limit) + 1;
  // Typed digits land here until they are committed, so "13" does not travel
  // through page 1 on its way in.
  const [draft, setDraft] = useState(String(page));
  useEffect(() => setDraft(String(page)), [page]);

  if (counted === 0) return null;

  let total = counted;
  let totalCapped = countCapped;
  if (keyset && countCapped) {
    const walked = skip + keyset.rows;
    total = keyset.hasNext ? Math.max(counted, walked) : walked;
    totalCapped = keyset.hasNext;
  }

  const totalPages = Math.max(1, Math.ceil(total / limit));
  const isFirst = page <= 1;
  const isLast = keyset
    ? !keyset.hasNext
    : !totalCapped && skip + limit >= total;
  const from = total === 0 ? 0 : skip + 1;
  const to = Math.min(skip + limit, total);
  const pagesLabel = totalCapped ? `${totalPages}+` : String(totalPages);

  const commitDraft = () => {
    const parsed = Number.parseInt(draft, 10);
    if (Number.isNaN(parsed)) {
      setDraft(String(page));
      return;
    }
    const clamped = Math.min(Math.max(parsed, 1), totalPages);
    setDraft(String(clamped));
    if (clamped !== page) onPageChange?.(clamped);
  };

  const sizes = pageSizeOptions.includes(limit)
    ? pageSizeOptions
    : [...pageSizeOptions, limit].sort((a, b) => a - b);

  const arrowClass =
    "h-11 w-11 md:h-10 md:w-10 flex items-center justify-center rounded-lg border border-border bg-surface-card hover:bg-surface-insed disabled:opacity-30 disabled:cursor-not-allowed transition-colors";

  return (
    <div className="mt-6 pb-6 flex flex-col sm:flex-row items-center justify-between gap-3 px-4 py-3 rounded-xl border border-border bg-surface-card">
      <div className="flex items-center gap-3">
        <span className="text-xs text-on-muted">
          {t("pagination.showing")}{" "}
          <span className="font-medium text-on tabular-nums">
            {from}–{to}
          </span>{" "}
          {t("pagination.of")}{" "}
          <span className="font-medium text-on tabular-nums">
            {totalCapped ? t("pagination.moreThan", { count: total }) : total}
          </span>
        </span>
        {onLimitChange && (
          <NativeSelect
            wrapperClassName="w-fit"
            aria-label={t("pagination.rowsPerPage")}
            value={String(limit)}
            onChange={(e) => onLimitChange(Number(e.target.value))}
            className="text-xs"
          >
            {sizes.map((size) => (
              <option key={size} value={size}>
                {t("pagination.rows", { count: size })}
              </option>
            ))}
          </NativeSelect>
        )}
      </div>
      <div className="flex items-center gap-2">
        <button
          disabled={isFirst}
          onClick={onPrev}
          className={arrowClass}
          aria-label={t("actions.previous")}
        >
          <ChevronLeft size={18} />
        </button>
        {onPageChange ? (
          <span className="flex items-center gap-1.5 text-sm font-semibold tabular-nums">
            <Input
              type="number"
              min={1}
              max={totalPages}
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onBlur={commitDraft}
              onKeyDown={(e) => {
                if (e.key === "Enter") commitDraft();
              }}
              aria-label={t("pagination.page")}
              wrapperClassName="w-16"
              className="text-center px-2"
            />
            <span className="text-on-muted">/</span>
            <span>{pagesLabel}</span>
          </span>
        ) : (
          <span className="text-sm font-semibold tabular-nums px-2">
            {page} / {pagesLabel}
          </span>
        )}
        <button
          disabled={isLast}
          onClick={onNext}
          className={arrowClass}
          aria-label={t("actions.next")}
        >
          <ChevronRight size={18} />
        </button>
      </div>
    </div>
  );
}
