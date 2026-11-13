import { useEffect, useState } from "react";
import { Search, SlidersHorizontal } from "lucide-react";
import { Input } from "@/components/ui/Input";
import { DateInput } from "@/components/ui/DateInput";
import { Button } from "@/components/ui/Button";
import { NativeSelect } from "@/components/ui/NativeSelect";
import {
  FilterChip,
  ListControlBar,
  RowLabel,
  type ListControlBarSecondaryFilter,
} from "@/components/ui/ListControlBar";
import { ScrollRow } from "@/components/ui/ScrollRow";
import { ScannerReadyHint } from "@/components/ui/ScannerReadyHint";
import { useScannerInput } from "@/hooks/useScannerInput";
import { cn } from "@/lib/utils";
import { DOCUMENT_DISCREPANCY_CODES } from "@/modules/warehouse/discrepancyCodes";
import { DOCUMENT_TYPES } from "@/modules/warehouse/types";
import type {
  DocumentDiscrepancyFilter,
  DocumentStatusFilter,
  DocumentTypeFilter,
  DocumentSortBy,
  DocumentSortOrder,
} from "@/modules/warehouse/hooks/useDocumentsList";

const TYPE_FILTERS: DocumentTypeFilter[] = ["ALL", ...DOCUMENT_TYPES];

const STATUS_OPTIONS: DocumentStatusFilter[] = [
  "ALL",
  "DRAFT",
  "PENDING_APPROVAL",
  "CONFIRMED",
  "COMPLETED",
  "CANCELLED",
];

interface DocumentsFiltersProps {
  search: string;
  setSearch: (value: string) => void;
  typeFilter: DocumentTypeFilter;
  setTypeFilter: (value: DocumentTypeFilter) => void;
  statusFilter: DocumentStatusFilter;
  setStatusFilter: (value: DocumentStatusFilter) => void;
  discrepancyFilter: DocumentDiscrepancyFilter;
  setDiscrepancyFilter: (value: DocumentDiscrepancyFilter) => void;
  dateFrom: string;
  setDateFrom: (value: string) => void;
  dateTo: string;
  setDateTo: (value: string) => void;
  sortBy: DocumentSortBy;
  sortOrder: DocumentSortOrder;
  setSortBy: (value: DocumentSortBy) => void;
  setSortOrder: (value: DocumentSortOrder) => void;
  /** The filters enabled modules add; the server answers each. */
  moduleFilters?: ListControlBarSecondaryFilter[];
  /** False while something else on the page reads the scanner. */
  scannerEnabled?: boolean;
  t: (key: string) => string;
}

export function DocumentsFilters({
  search,
  setSearch,
  typeFilter,
  setTypeFilter,
  statusFilter,
  setStatusFilter,
  discrepancyFilter,
  setDiscrepancyFilter,
  dateFrom,
  setDateFrom,
  dateTo,
  setDateTo,
  sortBy,
  sortOrder,
  setSortBy,
  setSortOrder,
  moduleFilters = [],
  scannerEnabled = true,
  t,
}: DocumentsFiltersProps) {
  // on phones the discrepancy/sort selects are collapsed behind a
  // "Filters" toggle with an active-count badge — they used to consume the
  // first screen permanently.
  const [filtersOpen, setFiltersOpen] = useState(false);
  // A code a hardware scanner reads — a document number, a partner's
  // reference — is a search, wherever the focus is, unless a picking session
  // is open over the page: that scan is the session's.
  useScannerInput(setSearch, { enabled: scannerEnabled });
  const activeFilterCount =
    (discrepancyFilter !== "ALL" ? 1 : 0) +
    (dateFrom ? 1 : 0) +
    (dateTo ? 1 : 0) +
    moduleFilters.filter((filter) => filter.active).length;
  // the phone list folds the whole filter area behind one toggle so
  // the first row lands on the first screen. A narrowed list reopens it —
  // the reader must see what is filtering the rows they look at.
  const isNarrowed =
    search !== "" ||
    typeFilter !== "ALL" ||
    statusFilter !== "ALL" ||
    discrepancyFilter !== "ALL" ||
    dateFrom !== "" ||
    dateTo !== "" ||
    moduleFilters.some((filter) => filter.active);
  const mobileFilterCount =
    (typeFilter !== "ALL" ? 1 : 0) +
    (statusFilter !== "ALL" ? 1 : 0) +
    activeFilterCount;

  useEffect(() => {
    if (isNarrowed) setFiltersOpen(true);
  }, [isNarrowed]);

  const renderSelectFilters = (idSuffix: string) => (
    <div className="flex flex-col gap-3">
      {/* When the document was written. The register has had this range
          since it was built and the list request has always accepted it;
          only this screen never asked for it, which left "sometime in
          March" as a reason to page through fifty rows. */}
      <div className="flex items-end gap-2">
        <DateInput
          id={`documents-date-from${idSuffix}`}
          label={t("warehouse:filters.dateFrom")}
          value={dateFrom}
          onChange={setDateFrom}
          wrapperClassName="w-36"
          className="text-sm"
        />
        <span className="mb-2 text-on-secondary">–</span>
        <DateInput
          id={`documents-date-to${idSuffix}`}
          label={t("warehouse:filters.dateTo")}
          value={dateTo}
          onChange={setDateTo}
          wrapperClassName="w-36"
          className="text-sm"
        />
      </div>

      <div className="flex-1 max-w-xs">
        <NativeSelect
          id={`documents-discrepancy-filter${idSuffix}`}
          label={t("warehouse:filters.discrepancyCode")}
          value={discrepancyFilter}
          onChange={(event) =>
            setDiscrepancyFilter(
              event.target.value as DocumentDiscrepancyFilter,
            )
          }
        >
          <option value="ALL">
            {t("warehouse:filters.allDiscrepancyCodes")}
          </option>
          {DOCUMENT_DISCREPANCY_CODES.map((code) => (
            <option key={code} value={code}>
              {t(`detail.discrepancyCodes.${code}`)}
            </option>
          ))}
        </NativeSelect>
      </div>

      <div className="flex-1 max-w-xs">
        <NativeSelect
          id={`documents-sort${idSuffix}`}
          label={t("warehouse:sort.label")}
          value={`${sortBy}_${sortOrder}`}
          onChange={(e) => {
            const parts = e.target.value.split("_");
            const order = parts.pop() as DocumentSortOrder;
            const by = parts.join("_") as DocumentSortBy;
            setSortBy(by);
            setSortOrder(order);
          }}
        >
          {/* Newest and oldest by the document's own date — the date the
              register, the period guard and the date filter above all read. */}
          <option value="document_date_desc">
            {t("warehouse:sort.newest")}
          </option>
          <option value="document_date_asc">
            {t("warehouse:sort.oldest")}
          </option>
          <option value="number_asc">{t("warehouse:sort.numberAsc")}</option>
          <option value="number_desc">{t("warehouse:sort.numberDesc")}</option>
        </NativeSelect>
      </div>

      {/* A module's filters, the same chips History shows them as; each is
          a question the server answers, so the count and the paging stay
          true. */}
      {moduleFilters.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {moduleFilters.map((filter) => (
            <FilterChip key={filter.key} filter={filter} />
          ))}
        </div>
      )}
    </div>
  );

  return (
    <>
      {/* Type filter - tabs on desktop, stacked on mobile */}
      <div className="hidden md:block">
        <ListControlBar
          search={{
            value: search,
            onChange: setSearch,
            placeholder: t("warehouse:searchPlaceholder"),
          }}
          primaryTabs={{
            // Both rows start with "All"; without the captions they read as one
            // filter in two states. The tabs name the type — `types`, which in
            // Polish is "Przyjęcie (PZ)" — because a tab is where a reader picks
            // a kind of work, and "PZ" alone names the code, not the work. The
            // dense register rows keep `typesShort` (see warehouse/types.ts).
            label: t("warehouse:filters.type"),
            value: typeFilter,
            onChange: (value) => setTypeFilter(value as DocumentTypeFilter),
            options: TYPE_FILTERS.map((tf) => ({
              value: tf,
              label: t("types." + tf),
            })),
          }}
          secondaryFiltersLabel={t("warehouse:filters.status")}
          secondaryFilters={STATUS_OPTIONS.map((s) => ({
            key: s,
            label: s === "ALL" ? t("warehouse:types.ALL") : t(`status.${s}`),
            active: statusFilter === s,
            onToggle: () => setStatusFilter(s),
          }))}
          // discrepancy + sort collapse behind the bar's filter
          // button (with active-count) instead of a permanent extra row.
          filterButton={{
            activeCount: activeFilterCount,
            onClick: () => setFiltersOpen((v) => !v),
          }}
        />
        {filtersOpen && (
          <div className="mt-3 max-w-sm">{renderSelectFilters("")}</div>
        )}
      </div>
      <div className="block md:hidden space-y-3">
        <div className="flex gap-2">
          <div className="flex-1 min-w-0">
            <Input
              // The phone layout has no room for a visible label, and the
              // placeholder is gone after the first keystroke.
              aria-label={t("warehouse:searchPlaceholder")}
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder={t("warehouse:searchPlaceholder")}
              leftIcon={<Search size={15} />}
            />
          </div>
          {/* one toggle folds type, status and the selects away;
              the count says how many of them bite. */}
          <Button
            variant="outline"
            size="sm"
            leftIcon={<SlidersHorizontal size={14} />}
            onClick={() => setFiltersOpen((v) => !v)}
            aria-expanded={filtersOpen}
            className="shrink-0"
          >
            {t("warehouse:filters.title")}
            {mobileFilterCount > 0 && ` (${mobileFilterCount})`}
          </Button>
        </div>
        {filtersOpen && (
          <div className="space-y-3">
            <div className="flex items-center gap-2">
              <RowLabel>{t("warehouse:filters.type")}</RowLabel>
              <div className="flex-1 min-w-0">
                <NativeSelect
                  // This control lives in the folded area and had no visible
                  // label — the RowLabel beside it names it for the eye as
                  // well as the tree.
                  aria-label={t("warehouse:filters.type")}
                  value={typeFilter}
                  onChange={(e) =>
                    setTypeFilter(e.target.value as DocumentTypeFilter)
                  }
                >
                  {TYPE_FILTERS.map((tf) => (
                    <option key={tf} value={tf}>
                      {t("types." + tf)}
                    </option>
                  ))}
                </NativeSelect>
              </div>
            </div>
            <div className="flex items-center gap-2">
              <RowLabel>{t("warehouse:filters.status")}</RowLabel>
              <ScrollRow
                role="group"
                aria-label={t("warehouse:filters.status")}
                className="flex gap-2 -mx-1 px-1"
              >
                {STATUS_OPTIONS.map((s) => (
                  // eslint-disable-next-line no-restricted-syntax -- chip-toggle styling (rounded-full pill) is not covered by Button variants
                  <button
                    key={s}
                    type="button"
                    onClick={() => setStatusFilter(s)}
                    // This row is phone-only, so the chip carries the full 44px
                    // touch target without a breakpoint. `shrink-0` is what makes
                    // the row scroll instead of squashing six chips into the
                    // viewport until their labels overlap.
                    className={cn(
                      "inline-flex shrink-0 items-center justify-center h-11 min-w-11 px-3 text-xs rounded-full whitespace-nowrap transition-colors",
                      statusFilter === s
                        ? "bg-primary-50 text-on font-medium ring-1 ring-primary-500"
                        : "bg-surface-raised text-on-secondary hover:text-on",
                    )}
                  >
                    {s === "ALL" ? t("warehouse:types.ALL") : t(`status.${s}`)}
                  </button>
                ))}
              </ScrollRow>
            </div>
            {renderSelectFilters("-mobile")}
          </div>
        )}
      </div>
      <ScannerReadyHint className="mt-2" />
    </>
  );
}
