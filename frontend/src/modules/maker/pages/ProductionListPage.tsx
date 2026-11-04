import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Calendar, Hammer, Plus } from "lucide-react";
import { Link, useNavigate } from "react-router-dom";
import { useModulePageHeader } from "@/hooks/useModulePageHeader";
import { QueryFailure } from "@/components/ui/QueryResult";
import { showListControls } from "@/hooks/useFilteredList";
import { useLocalStorage } from "@/hooks/useLocalStorage";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { ListControlBar } from "@/components/ui/ListControlBar";
import { Pagination } from "@/module-sdk";
import { useProductionOrders } from "@/modules/maker/hooks/useProduction";
import { useDuplicateOrderNavigation } from "@/modules/maker/hooks/useDuplicateOrderNavigation";
import { DuplicateOrderButton } from "@/modules/maker/components/DuplicateOrderButton";
import { useCanWrite } from "@/hooks/useCanWrite";
import { ReadOnlyNotice } from "@/components/ui/ReadOnlyNotice";
import { ProductionCreateSheet } from "@/modules/maker/components/ProductionCreateSheet";
import { ProductionListFilters } from "@/modules/maker/components/ProductionListFilters";
import { ProductionStatusBadge } from "@/modules/maker/components/ProductionStatusBadge";
import { ProductionTable } from "@/modules/maker/components/ProductionTable";
import type {
  ProductionOrder,
  ProductionStatus,
} from "@/modules/maker/types/maker";
import { formatDate } from "@/utils/helpers";
import { useOrganizationCurrency } from "@/hooks/useOrganizationCurrency";
import { formatMoney } from "@/utils/formatters";
import { ProductionShortageSignal } from "@/modules/maker/components/ProductionShortageSignal";
import { formatQuantityLocalized, unitLabel } from "@/lib/i18nHelpers";
import { useResultTerms } from "@/modules/maker/hooks/useResultTerms";

const STATUS_FILTERS: (ProductionStatus | "ALL")[] = [
  "ALL",
  "DRAFT",
  "COMPLETED",
  "CANCELLED",
];

/** Cards or rows — see the catalog: the choice is remembered per list. */
const VIEW_STORAGE_KEY = "maker:production-view";

const PAGE_LIMIT = 50;

/**
 * Which of the four things the list has to say.
 *
 * Deriving it once beats re-deriving it at each render site: the branches used
 * to spell out "not failed and not loading and empty", and every new state had
 * to be subtracted again from the ones after it.
 */
type ListState = "error" | "loading" | "empty" | "ready";

function listStateOf(
  isError: boolean,
  isLoading: boolean,
  count: number,
): ListState {
  if (isError) return "error";
  if (isLoading) return "loading";
  return count === 0 ? "empty" : "ready";
}

/**
 * The card's cost line. A snapshot only a completed run can write — drafts
 * read the dash honestly.
 */
function CardCost({
  totalCost,
  currency,
  language,
}: {
  totalCost: string | null;
  currency: string | undefined;
  language: string;
}) {
  const { t } = useTranslation("maker");
  return (
    <div className="text-on-muted text-xs mt-1">
      {t("productionList.card.cost")}:{" "}
      {totalCost === null ? "—" : formatMoney(totalCost, currency, language)}
    </div>
  );
}

/**
 * The card's financial result: a snapshot, per unit × actual output, that only
 * a completed run carries. Named and defined the way every production screen
 * names it.
 */
function CardResult({
  order,
  currency,
  language,
}: {
  order: ProductionOrder;
  currency: string | undefined;
  language: string;
}) {
  const { t } = useTranslation("maker");
  const resultTerm = useResultTerms();
  if (
    order.status !== "COMPLETED" ||
    order.result_per_unit === null ||
    order.actual_qty === null
  ) {
    return null;
  }
  return (
    <div className="text-xs mt-1">
      <p
        className={`font-medium ${
          Number(order.result_per_unit) >= 0
            ? "text-accent-600"
            : "text-red-500"
        }`}
      >
        {resultTerm.label}:{" "}
        {formatMoney(
          Number(order.result_per_unit) * Number(order.actual_qty),
          currency,
          language,
        )}
        <span className="text-on-muted font-normal">
          {" "}
          {t("productionList.card.resultPerUnit", {
            amount: formatMoney(order.result_per_unit, currency, language),
            unit:
              unitLabel(t, order.output_uom_symbol) ||
              t("create.needs.unitFallback"),
          })}
        </span>
      </p>
      {/* Written on the card, as on a BOM card: a hover title never
          reached a finger. */}
      <p className="text-on-muted">{resultTerm.definition}</p>
    </div>
  );
}

export default function ProductionListPage() {
  const currency = useOrganizationCurrency();
  const { t, i18n } = useTranslation("maker");
  const navigate = useNavigate();
  const { setHeader } = useModulePageHeader();

  const [statusFilter, setStatusFilter] = useState<ProductionStatus | "ALL">(
    "ALL",
  );
  const [search, setSearch] = useState("");
  const [showCreate, setShowCreate] = useState(false);
  const [sort, setSort] = useState("newest");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [showFilters, setShowFilters] = useState(false);
  const [skip, setSkip] = useState(0);
  const [viewMode, setViewMode] = useLocalStorage<"grid" | "list">(
    VIEW_STORAGE_KEY,
    "grid",
  );

  const activeFilterCount =
    (sort !== "newest" ? 1 : 0) + (dateFrom ? 1 : 0) + (dateTo ? 1 : 0);
  const hasActiveFilters = activeFilterCount > 0;

  const statusParam =
    statusFilter === "ALL" ? undefined : (statusFilter as ProductionStatus);
  const {
    data: listResponse,
    isLoading,
    isError,
    error,
    refetch,
  } = useProductionOrders({
    status: statusParam,
    sort,
    date_from: dateFrom || undefined,
    date_to: dateTo || undefined,
    skip,
    limit: PAGE_LIMIT,
  });

  const orders = useMemo(() => listResponse?.items ?? [], [listResponse]);
  const total = listResponse?.total ?? 0;
  const isNarrowed =
    search.trim().length > 0 || statusFilter !== "ALL" || hasActiveFilters;
  const controlsVisible = showListControls({ isLoading, total, isNarrowed });

  const { duplicate, isDuplicating } = useDuplicateOrderNavigation();
  // Duplicating an order writes one. An account that may only read the list
  // used to be offered the action and refused at the end of it.
  const canWrite = useCanWrite("maker");

  const filteredOrders = useMemo(() => {
    if (!search.trim()) return orders;
    const needle = search.toLowerCase();
    return orders.filter(
      (order) =>
        (order.output_template_name ?? "").toLowerCase().includes(needle) ||
        (order.number ?? "").toLowerCase().includes(needle) ||
        (order.output_template_id ?? "").toLowerCase().includes(needle),
    );
  }, [orders, search]);

  const listState = listStateOf(isError, isLoading, filteredOrders.length);

  useEffect(() => {
    setSkip(0);
  }, [statusFilter, sort, dateFrom, dateTo]);

  useEffect(() => {
    setHeader({
      title: t("productionList.title"),
      subtitle: t("productionList.subtitle"),
      actions: canWrite ? (
        <div className="ml-auto flex gap-2">
          <Button
            onClick={() => setShowCreate(true)}
            leftIcon={<Plus size={16} />}
          >
            {t("productionList.newProduction")}
          </Button>
        </div>
      ) : undefined,
    });
  }, [t, setHeader, navigate, canWrite]);

  return (
    <div className="space-y-6 animate-in fade-in slide-in-from-bottom-4 duration-500">
      <ReadOnlyNotice module="maker" />
      {controlsVisible && (
        <ListControlBar
          search={{
            value: search,
            onChange: setSearch,
            placeholder: t("productionList.searchPlaceholder"),
          }}
          resultCount={search ? filteredOrders.length : undefined}
          primaryTabs={{
            value: statusFilter,
            onChange: (value) =>
              setStatusFilter(value as ProductionStatus | "ALL"),
            options: STATUS_FILTERS.map((status) => ({
              value: status,
              label: t(`productionList.status.${status.toLowerCase()}`, {
                defaultValue: status,
              }),
            })),
          }}
          filterButton={{
            activeCount: activeFilterCount,
            onClick: () => setShowFilters((prev) => !prev),
          }}
          viewToggle={{ mode: viewMode, onChange: setViewMode }}
        />
      )}

      {controlsVisible && showFilters && (
        <ProductionListFilters
          sort={sort}
          dateFrom={dateFrom}
          dateTo={dateTo}
          hasActiveFilters={hasActiveFilters}
          onSortChange={setSort}
          onDateFromChange={setDateFrom}
          onDateToChange={setDateTo}
          onReset={() => {
            setSort("newest");
            setDateFrom("");
            setDateTo("");
          }}
        />
      )}

      {listState === "error" && (
        <QueryFailure
          error={error}
          message={t("productionList.error")}
          onRetry={() => refetch()}
        />
      )}

      {listState === "loading" && (
        <div className="flex flex-col items-center justify-center py-16">
          <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-accent-600 mb-4" />
          <p className="text-on-muted font-medium uppercase tracking-widest text-[10px]">
            {t("productionList.loading")}
          </p>
        </div>
      )}

      {listState === "empty" && (
        <Card className="p-12 text-center border border-dashed border-border bg-surface-card">
          <Hammer size={48} className="mx-auto text-on-muted mb-4" />
          <h3 className="text-xl font-semibold text-on mb-2">
            {isNarrowed
              ? t("productionList.noMatches.title")
              : t("productionList.empty.title")}
          </h3>
          <p className="text-on-secondary mb-8">
            {isNarrowed
              ? t("productionList.noMatches.subtitle")
              : t("productionList.empty.subtitle")}
          </p>
          {/* Nothing to create from a search that found nothing — the CTA
              belongs to the genuinely empty list, and to an account that
              could submit the form. */}
          {!isNarrowed && canWrite && (
            <Button
              onClick={() => setShowCreate(true)}
              leftIcon={<Plus size={16} />}
            >
              {t("productionList.newProduction")}
            </Button>
          )}
        </Card>
      )}

      {/* An empty table is a header over nothing — the empty state above
          already speaks for a list with no rows. */}
      {listState === "ready" &&
        (viewMode === "list" ? (
          <ProductionTable
            orders={filteredOrders}
            sort={sort}
            onDuplicate={canWrite ? duplicate : undefined}
            isDuplicating={isDuplicating}
          />
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {filteredOrders.map((order) => (
              <Card
                key={order.id}
                className="p-4 hover:shadow-md transition-shadow cursor-pointer"
                onClick={() => navigate(`/maker/production/${order.id}`)}
              >
                <div className="flex items-start justify-between gap-3">
                  <h2 className="font-semibold text-sm truncate">
                    {/* The number is what tells two runs on the same product
                        apart; the product name alone never did. A legacy run
                        without a number falls back to the short UUID. */}
                    <Link
                      to={`/maker/production/${order.id}`}
                      className="hover:text-accent focus-visible:text-accent"
                    >
                      {order.output_template_name ?? (
                        <span className="font-mono text-xs text-on-muted">
                          {order.id.slice(0, 8)}…
                        </span>
                      )}
                    </Link>
                    {order.number && (
                      <span
                        className="ml-2 font-mono text-xs text-on-muted font-normal"
                        data-testid="maker-order-number"
                      >
                        {order.number}
                      </span>
                    )}
                  </h2>
                  <ProductionStatusBadge status={order.status} />
                </div>
                <div className="mt-3 text-sm">
                  <div className="font-semibold">
                    {t("productionList.card.qty")}:{" "}
                    {formatQuantityLocalized(
                      t,
                      order.planned_qty,
                      order.output_uom_symbol,
                    )}
                  </div>
                  <CardCost
                    totalCost={order.total_cost}
                    currency={currency}
                    language={i18n.language}
                  />
                  <ProductionShortageSignal count={order.shortage_count} />
                  <CardResult
                    order={order}
                    currency={currency}
                    language={i18n.language}
                  />
                  <div className="text-on-muted text-xs mt-1 flex items-center gap-1">
                    <Calendar size={12} />
                    {formatDate(order.created_at)}
                  </div>
                </div>
                <div className="mt-2 flex justify-end gap-2">
                  {/* Pre-0a orders carry no recipe reference. There is nothing
                    to open for them now that the by-product editor is gone —
                    an offer that leads nowhere is worse than no offer. */}
                  {order.recipe_id && (
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={(e) => {
                        e.stopPropagation();
                        navigate(`/maker/recipes/${order.recipe_id}`);
                      }}
                      data-testid="maker-card-view-recipe-button"
                    >
                      {t("productionList.viewRecipe")}
                    </Button>
                  )}
                  {canWrite && (
                    <DuplicateOrderButton
                      orderId={order.id}
                      isDuplicating={isDuplicating}
                      onDuplicate={duplicate}
                      testId="maker-card-duplicate-button"
                    />
                  )}
                </div>
              </Card>
            ))}
          </div>
        ))}

      <Pagination
        skip={skip}
        limit={PAGE_LIMIT}
        total={total}
        onPrev={() => setSkip(Math.max(0, skip - PAGE_LIMIT))}
        onNext={() => setSkip(skip + PAGE_LIMIT)}
      />

      <ProductionCreateSheet
        open={showCreate}
        onClose={() => setShowCreate(false)}
        onSuccess={(orderId) => {
          setShowCreate(false);
          navigate(`/maker/production/${orderId}`);
        }}
      />
    </div>
  );
}
