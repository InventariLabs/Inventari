/**
 * StockMovesPage — /inventory/moves
 *
 * The organization's movement ledger: what came in, what left, what moved
 * between its own places, and who recorded it. Every path that changes
 * physical stock writes one of these rows, and until now none of them was
 * visible anywhere in the application.
 *
 * Nobody comes to a ledger asking for everything, so the controls are the
 * questions a warehouse actually asks: which direction, which place (and
 * everything below it), and which stretch of days. The rest of the filters
 * the endpoint takes are reached from the screens that own their subject —
 * a product's history, a batch's path, a document's effect.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { pageTotal } from "@/modules/inventory/utils/pageTotal";
import { useTranslation } from "react-i18next";
import type { TFunction } from "i18next";
import { ArrowLeftRight, FileDown, X } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { ListControlBar } from "@/components/ui/ListControlBar";
import { EmptyState } from "@/components/ui/EmptyState";
import { LocationCombobox } from "@/module-sdk";
import { useLocationsById } from "@/module-sdk";
import { DateInput } from "@/components/ui/DateInput";
import { Card } from "@/components/ui/Card";
import { Pagination } from "@/module-sdk";
import LoadingSpinner from "@/components/LoadingSpinner";
import { QueryFailure } from "@/components/ui/QueryResult";
import { useModulePageHeader } from "@/hooks/useModulePageHeader";
import { useFilteredList } from "@/hooks/useFilteredList";
import { useKeysetPaging } from "@/hooks/useKeysetPaging";
import { toast } from "sonner";
import {
  downloadBlob,
  getStorageLocationPath,
  type LocationPathNode,
} from "@/utils/helpers";
import { getTodayFilename, formatDate } from "@/utils/formatters";
import { extractApiError } from "@/lib/errors";
import { stockMovesApi } from "@/lib/api/stockMoves";
import { useStockMoves } from "../hooks/useStockMoves";
import { useShowModuleData } from "@/modules/settings/hooks/useOrganization";
import { StockMovesTable } from "../components/StockMovesTable";
import { StockMoveCards } from "../components/StockMoveCards";
import type { StockMoveDirection } from "@/lib/api/stockMoves";

const PAGE_SIZE = 50;

const DIRECTIONS: (StockMoveDirection | "all")[] = [
  "all",
  "in",
  "out",
  "internal",
];

/** What is narrowing the ledger right now, in the screen's own terms. */
export interface MoveFilterNames {
  direction: StockMoveDirection | "all";
  locationName: string | undefined;
  since: string;
  until: string;
  productName: string | undefined;
}

/**
 * The filters the reader actually set, named the way the controls name
 * them. The empty state used to advise widening "the dates" and clearing
 * "the storage" whatever was on: a reader whose only narrowing was a
 * direction tab was sent looking for controls that were not even open.
 */
export function describeMoveFilters(
  t: TFunction,
  filters: MoveFilterNames,
): string[] {
  const names: string[] = [];
  if (filters.direction !== "all") {
    names.push(
      t("inventory:moves.empty.filterNames.direction", {
        value: t(`inventory:moves.direction.${filters.direction}`),
      }),
    );
  }
  if (filters.locationName) {
    names.push(
      t("inventory:moves.empty.filterNames.location", {
        value: filters.locationName,
      }),
    );
  }
  if (filters.since && filters.until) {
    names.push(
      t("inventory:moves.empty.filterNames.dates", {
        from: formatDate(filters.since),
        to: formatDate(filters.until),
      }),
    );
  } else if (filters.since) {
    // One end only: "from 08/01/2026", never "08/01/2026 – —". The dash
    // with nothing behind it reads as a rendering fault, and it is the
    // shape the reader reaches most often.
    names.push(
      t("inventory:moves.empty.filterNames.datesFrom", {
        date: formatDate(filters.since),
      }),
    );
  } else if (filters.until) {
    names.push(
      t("inventory:moves.empty.filterNames.datesUntil", {
        date: formatDate(filters.until),
      }),
    );
  }
  if (filters.productName) {
    names.push(
      t("inventory:moves.empty.filterNames.product", {
        value: filters.productName,
      }),
    );
  }
  return names;
}

/** The name of the location filter, or the fallback the hint prints. A
 *  location the picker cannot resolve must still be named: the ledger is
 *  narrowed either way, and "filters you set ()" tells the reader nothing.
 *  The fallback covers what even the archived-inclusive read cannot name —
 *  a deleted row, a failed request — the way a product filter falls back
 *  to "one product". */
function locationFilterName(
  t: TFunction,
  locations: LocationPathNode[],
  locationId: string,
): string | undefined {
  if (!locationId) {
    return undefined;
  }
  const chosen = locations.find((candidate) => candidate.id === locationId);
  return chosen
    ? getStorageLocationPath(chosen, undefined, {}, locations)
    : t("inventory:moves.filters.oneStorage");
}

export default function StockMovesPage() {
  const { t } = useTranslation(["inventory", "common"]);
  const { setHeader } = useModulePageHeader();

  // The subject screens link here to widen their own question — a product's
  // tab asks for that product everywhere, a location's section for that
  // location on its own page. Every filter the reader sets is written back
  // to the address, so a refresh keeps the question and a copied link shows
  // a colleague the same list rather than a wider one.
  const list = useFilteredList(
    {
      template: { default: "", urlKey: "template" },
      direction: { default: "all", urlKey: "direction" },
      location: { default: "", urlKey: "location" },
      since: { default: "", urlKey: "since" },
      until: { default: "", urlKey: "until" },
    },
    { syncToUrl: true },
  );
  const templateId = String(list.values.template);
  // An address is typed by hand too: a direction the ledger does not know
  // reads as all of them rather than as a refused request.
  const direction =
    DIRECTIONS.find((value) => value === list.values.direction) ?? "all";
  const locationId = String(list.values.location);
  const since = String(list.values.since);
  const until = String(list.values.until);
  const [showFilters, setShowFilters] = useState(false);

  useEffect(() => {
    setHeader({
      title: t("inventory:moves.title"),
      subtitle: t("inventory:moves.subtitle"),
    });
  }, [setHeader, t]);

  // The place the filter names, read by id. Archived storages come along:
  // the link that narrows this ledger is written on a storage's own card, and
  // archiving the storage afterwards must not turn its name into an empty
  // parenthesis.
  const { byId: namedPlaces } = useLocationsById([locationId]);
  const locations = useMemo(() => [...namedPlaces.values()], [namedPlaces]);

  // The journal the overview links to follows the overview's rule, so "view
  // all" never opens more than the card was a sample of.
  const excludeModuleContexts = !useShowModuleData();
  const question = useMemo(
    () => ({
      direction: direction === "all" ? undefined : direction,
      product_template_id: templateId || undefined,
      location_id: locationId || undefined,
      since: since || undefined,
      until: until || undefined,
      exclude_module_contexts: excludeModuleContexts,
    }),
    [direction, templateId, locationId, since, until, excludeModuleContexts],
  );

  // Any change to the question starts the answer from its first page: a
  // filter applied on page four would otherwise leave the reader holding a
  // position in a different list.
  const paging = useKeysetPaging(question);

  const filters = useMemo(
    () => ({ ...question, limit: PAGE_SIZE, cursor: paging.cursor }),
    [question, paging.cursor],
  );

  const { data, isLoading, isError, error, isPlaceholderData, refetch } =
    useStockMoves(filters);
  const moves = data?.items ?? [];
  // A large organization's list stops counting at `total` and says so.
  const { total, totalCapped } = pageTotal(data);

  // The file answers the question on screen, so it takes the filters and
  // leaves the paging behind.
  const handleExport = useCallback(async () => {
    try {
      toast.loading(t("common:actions.exporting"), { id: "moves-export" });
      const blob = await stockMovesApi.exportXlsx(question);
      downloadBlob(blob, `stock_moves_${getTodayFilename()}.xlsx`);
      toast.success(t("common:actions.exportSuccess"), { id: "moves-export" });
    } catch (error) {
      // The refusal carries the reason -- how many rows matched, and that
      // the range needs narrowing. Swallowing it for a generic "export
      // failed" leaves the reader with no way to succeed.
      toast.error(extractApiError(error, t("common:actions.exportError")), {
        id: "moves-export",
      });
    }
  }, [question, t]);

  const activeFilterCount =
    (locationId ? 1 : 0) + (since ? 1 : 0) + (until ? 1 : 0);
  const narrowed =
    activeFilterCount > 0 || direction !== "all" || Boolean(templateId);

  // A location the picker cannot name still has to be named: the ledger is
  // narrowed either way, and "filters you set ()" tells the reader nothing.
  const locationName = locationFilterName(t, locations, locationId);

  const activeFilters = describeMoveFilters(t, {
    direction,
    locationName,
    since,
    until,
    productName: templateId
      ? (moves[0]?.product_name ?? t("inventory:moves.filters.oneProduct"))
      : undefined,
  });

  return (
    <div className="space-y-6">
      <ListControlBar
        primaryTabs={{
          value: direction,
          onChange: (value) => list.setFilter("direction", value),
          options: DIRECTIONS.map((value) => ({
            value,
            label: t(`inventory:moves.direction.${value}`),
          })),
        }}
        filterButton={{
          activeCount: activeFilterCount,
          onClick: () => setShowFilters((previous) => !previous),
        }}
        resultCount={isError ? undefined : total}
        resultCountCapped={totalCapped}
        resultCountLabel={t("inventory:moves.movements", { count: total })}
        primaryAction={
          <Button
            variant="outline"
            onClick={() => void handleExport()}
            leftIcon={<FileDown size={16} />}
            disabled={total === 0}
          >
            {t("common:actions.export")}
          </Button>
        }
      />

      {showFilters && (
        <Card className="p-4">
          <div className="flex flex-wrap items-end gap-3">
            <LocationCombobox
              label={t("inventory:moves.filters.location")}
              title={t("inventory:moves.filters.location")}
              wrapperClassName="w-full sm:w-64"
              // Archived places too: a card links here with its own place.
              scope={{ includeArchived: true }}
              value={locationId}
              onChange={(value) => list.setFilter("location", value)}
              placeholder={t("inventory:moves.filters.anyLocation")}
              searchPlaceholder={t("common:actions.search")}
              emptyMessage={t("common:noResults")}
              clearable
              clearLabel={t("inventory:moves.filters.anyLocation")}
            />
            <DateInput
              label={t("inventory:moves.filters.since")}
              value={since}
              onChange={(value) => list.setFilter("since", value)}
              presets={["minus1Week", "minus1Month"]}
              wrapperClassName="w-full sm:w-44"
            />
            <DateInput
              label={t("inventory:moves.filters.until")}
              value={until}
              onChange={(value) => list.setFilter("until", value)}
              presets={["today", "yesterday"]}
              wrapperClassName="w-full sm:w-44"
            />
          </div>
        </Card>
      )}

      {/* The product filter has no control of its own -- it arrives from a
          product's own card -- so it has to be visible and removable, or the
          reader is looking at a narrowed ledger with nothing saying so. The
          name comes off the rows rather than a second request. */}
      {templateId && (
        <div className="flex items-center gap-2">
          <span className="text-sm text-on-secondary">
            {t("inventory:moves.filters.product")}
          </span>
          <Button
            variant="secondary"
            size="sm"
            onClick={() => list.setFilter("template", "")}
            rightIcon={<X size={14} aria-hidden="true" />}
          >
            {moves[0]?.product_name ?? t("inventory:moves.filters.oneProduct")}
            <span className="sr-only">{t("common:actions.clear")}</span>
          </Button>
        </div>
      )}

      {isError ? (
        <QueryFailure error={error} onRetry={() => void refetch()} />
      ) : isLoading ? (
        <LoadingSpinner />
      ) : moves.length === 0 ? (
        // Two different emptinesses. "Nothing has moved yet" is false the
        // moment a filter is on: something moved, just not this. Saying it
        // anyway sends the reader looking for a fault in the warehouse
        // instead of in the question they asked.
        <EmptyState
          icon={ArrowLeftRight}
          title={
            narrowed
              ? t("inventory:moves.empty.filteredTitle")
              : t("inventory:moves.empty.title")
          }
          description={
            narrowed
              ? t("inventory:moves.empty.filtered", {
                  count: activeFilters.length,
                  filters: activeFilters.join(" · "),
                })
              : t("inventory:moves.empty.description")
          }
        />
      ) : (
        <>
          <div className="hidden md:block">
            <StockMovesTable moves={moves} />
          </div>
          <div className="md:hidden">
            <StockMoveCards moves={moves} />
          </div>
          <Pagination
            skip={paging.page * PAGE_SIZE}
            limit={PAGE_SIZE}
            total={total}
            totalCapped={totalCapped}
            keyset={{ rows: moves.length, hasNext: Boolean(data?.next_cursor) }}
            onPrev={paging.goPrev}
            // The cursor on screen belongs to the page it came with; while the
            // next page loads the old rows are still shown, and their cursor
            // must not be taken for the new page's.
            onNext={() =>
              !isPlaceholderData && paging.goNext(data?.next_cursor)
            }
          />
        </>
      )}
    </div>
  );
}
