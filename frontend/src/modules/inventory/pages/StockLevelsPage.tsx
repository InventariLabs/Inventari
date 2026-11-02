/**
 * StockLevelsPage — /inventory/stock
 *
 * What lies where. The product list answers "what do we have" from the
 * `Item.quantity` cache, one row per record; this answers the question a
 * warehouse actually works from — how much of a product is at one place, out
 * of which batch, and how much of it is already promised.
 *
 * Rows arrive ordered by place, so a location reads as a block without a
 * grouping widget. Reservations are a column, never a subtraction: "six on
 * the shelf, four promised" and "two on the shelf" are different sentences.
 */
import { useEffect, useMemo, useState } from "react";
import { pageTotal } from "@/modules/inventory/utils/pageTotal";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import type { TFunction } from "i18next";
import { Boxes, CalendarClock, Layers, X } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { ListControlBar } from "@/components/ui/ListControlBar";
import { LocationCombobox } from "@/module-sdk";
import { useLocationsById } from "@/module-sdk";
import { Card } from "@/components/ui/Card";
import { Checkbox } from "@/components/ui/Checkbox";
import { EmptyState } from "@/components/ui/EmptyState";
import { Pagination } from "@/module-sdk";
import LoadingSpinner from "@/components/LoadingSpinner";
import { QueryFailure } from "@/components/ui/QueryResult";
import { useFilteredList } from "@/hooks/useFilteredList";
import { useModulePageHeader } from "@/hooks/useModulePageHeader";
import { useReturnTarget } from "@/hooks/useReturnTarget";
import { getStorageLocationPath, type LocationPathNode } from "@/utils/helpers";
import { useStockQuants } from "../hooks/useStockQuants";
import { StockQuantsTable } from "../components/stock/StockQuantsTable";
import { StockQuantCards } from "../components/stock/StockQuantCards";

const PAGE_SIZE = 50;

/** The filters the empty state names, and only those: with a search alone it
 *  used to send the reader to clear a storage nobody had picked — the same
 *  rule the movements ledger learned. The include-empty toggle widens rather
 *  than narrows, so it takes no part in the sentence. */
function appliedStockFilters(
  t: TFunction,
  {
    locations,
    locationId,
    templateId,
    productName,
    search,
  }: {
    locations: LocationPathNode[];
    locationId: string;
    templateId: string;
    productName: string | null | undefined;
    search: string;
  },
): string[] {
  const chosen = locations.find((candidate) => candidate.id === locationId);
  const locationName = locationId
    ? chosen
      ? getStorageLocationPath(chosen, undefined, {}, locations)
      : t("inventory:stock.filters.oneStorage")
    : undefined;
  return [
    locationName &&
      t("inventory:stock.empty.filterNames.location", { value: locationName }),
    templateId &&
      t("inventory:stock.empty.filterNames.product", {
        value: productName ?? t("inventory:stock.filters.oneProduct"),
      }),
    search.trim() &&
      t("inventory:stock.empty.filterNames.search", { value: search.trim() }),
  ].filter((name): name is string => Boolean(name));
}

export default function StockLevelsPage() {
  const { t } = useTranslation(["inventory", "common"]);
  const { setHeader } = useModulePageHeader();
  const navigate = useNavigate();
  const backTo = useReturnTarget();

  // The same factory the product list of this module narrows with: a debounced
  // search field in the shared bar, filters that answer to the URL, and a page
  // that resets when either of them changes. This screen had none of it — the
  // test organization had 143 rows on three pages and nothing to name a product
  // with — and two screens of one module should not ask the reader to search
  // two different ways. `location` and `template` are the param names other
  // screens already link with (`?template=` arrives from a product's card).
  const filters = useFilteredList(
    {
      location: { default: "", urlKey: "location" },
      product: { default: "", urlKey: "template" },
      includeEmpty: { default: false, urlKey: "include_empty" },
    },
    { searchDebounceMs: 400, limit: PAGE_SIZE, syncToUrl: true },
  );

  const locationId = String(filters.values.location);
  const templateId = String(filters.values.product);
  const includeEmpty = Boolean(filters.values.includeEmpty);
  const [showFilters, setShowFilters] = useState(false);

  useEffect(() => {
    setHeader({
      title: t("inventory:stock.title"),
      subtitle: t("inventory:stock.subtitle"),
      backTo,
    });
  }, [setHeader, t, backTo]);

  // The place the filter names, read by id. Archived places are nameable:
  // the link that narrows this list is written on a storage's card, and
  // archiving the storage afterwards must not leave the filter nameless.
  const { byId: namedPlaces } = useLocationsById([locationId]);
  const locations = useMemo(() => [...namedPlaces.values()], [namedPlaces]);

  const quantFilters = useMemo(
    () => ({
      location_id: locationId || undefined,
      product_template_id: templateId || undefined,
      include_empty: includeEmpty || undefined,
      // What the reader typed, sent to the server. A narrowed page is the
      // answer to "how much of this lies here", so it cannot be a filter over
      // the fifty rows this page happens to hold.
      search: filters.search || undefined,
      limit: filters.limit,
      offset: filters.skip,
    }),
    [
      locationId,
      templateId,
      includeEmpty,
      filters.search,
      filters.limit,
      filters.skip,
    ],
  );

  const { data, isLoading, isError, error, refetch } =
    useStockQuants(quantFilters);
  const rows = data?.items ?? [];
  // A large organization's list stops counting at `total` and says so.
  const { total, totalCapped } = pageTotal(data);

  const activeFilterCount =
    (locationId ? 1 : 0) + (includeEmpty ? 1 : 0) + (templateId ? 1 : 0);

  // The empty state names only the filters that are set — see
  // :func:`appliedStockFilters`.
  const appliedFilters = appliedStockFilters(t, {
    locations,
    locationId,
    templateId,
    productName: rows[0]?.product_name,
    search: filters.search,
  });

  return (
    <div className="space-y-6">
      <ListControlBar
        search={{
          value: filters.searchInput,
          onChange: filters.setSearchInput,
          placeholder: t("inventory:stock.searchPlaceholder"),
        }}
        filterButton={{
          activeCount: activeFilterCount,
          onClick: () => setShowFilters((previous) => !previous),
        }}
        resultCount={isError ? undefined : total}
        resultCountCapped={totalCapped}
        resultCountLabel={t("inventory:stock.rows", { count: total })}
        primaryAction={
          // The batches are their own list, and the only place a recall can
          // be entered. Reached from here rather than from the navigation:
          // a fourth stock entry in the menu buries the three that matter
          // daily.
          <>
            <Button
              variant="outline"
              leftIcon={<Layers size={16} />}
              onClick={() => navigate("/inventory/lots")}
            >
              {t("inventory:lots.title")}
            </Button>
            <Button
              variant="outline"
              leftIcon={<CalendarClock size={16} />}
              onClick={() => navigate("/inventory/stock/as-of")}
            >
              {t("inventory:asOf.title")}
            </Button>
          </>
        }
      />

      {showFilters && (
        <Card className="p-4">
          <div className="flex flex-wrap items-end gap-4">
            <LocationCombobox
              label={t("inventory:stock.filters.location")}
              title={t("inventory:stock.filters.location")}
              wrapperClassName="w-full sm:w-64"
              // Archived places too: a card links here with its own place.
              scope={{ includeArchived: true }}
              value={locationId}
              onChange={(id) => filters.setFilter("location", id)}
              placeholder={t("inventory:stock.filters.anyLocation")}
              searchPlaceholder={t("common:actions.search")}
              emptyMessage={t("common:noResults")}
              clearable
              clearLabel={t("inventory:stock.filters.anyLocation")}
            />
            <Checkbox
              label={
                <span className="text-sm text-on-secondary">
                  {t("inventory:stock.filters.includeEmpty")}
                  <span className="block text-xs text-on-muted">
                    {t("inventory:stock.filters.includeEmptyHint")}
                  </span>
                </span>
              }
              checked={includeEmpty}
              onChange={(event) =>
                filters.setFilter("includeEmpty", event.target.checked)
              }
            />
          </div>
        </Card>
      )}

      {/* The product filter arrives from a product's own card and has no
          control of its own, so it has to be visible and removable — a
          narrowed list with nothing saying so is a wrong answer. */}
      {templateId && (
        <div className="flex flex-wrap items-center gap-2">
          {templateId && (
            <>
              <span className="text-sm text-on-secondary">
                {t("inventory:moves.filters.product")}
              </span>
              <Button
                variant="secondary"
                size="sm"
                onClick={() => filters.setFilter("product", "")}
                rightIcon={<X size={14} aria-hidden="true" />}
              >
                {rows[0]?.product_name ??
                  t("inventory:moves.filters.oneProduct")}
                <span className="sr-only">{t("common:actions.clear")}</span>
              </Button>
            </>
          )}
        </div>
      )}

      {isError ? (
        <QueryFailure error={error} onRetry={() => void refetch()} />
      ) : isLoading ? (
        <LoadingSpinner />
      ) : rows.length === 0 ? (
        <EmptyState
          icon={Boxes}
          title={
            appliedFilters.length > 0
              ? t("inventory:stock.empty.filteredTitle")
              : t("inventory:stock.empty.title")
          }
          description={
            appliedFilters.length > 0
              ? t("inventory:stock.empty.filtered", {
                  count: appliedFilters.length,
                  filters: appliedFilters.join(" · "),
                })
              : t("inventory:stock.empty.description")
          }
        />
      ) : (
        <>
          <div className="hidden md:block">
            <StockQuantsTable rows={rows} />
          </div>
          <div className="md:hidden">
            <StockQuantCards rows={rows} />
          </div>
          <Pagination
            skip={filters.skip}
            limit={filters.limit}
            total={total}
            totalCapped={totalCapped}
            onPrev={filters.onPrev}
            onNext={filters.onNext}
            onPageChange={(next) => filters.setSkip((next - 1) * filters.limit)}
          />
        </>
      )}
    </div>
  );
}
