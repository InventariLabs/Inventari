import { useTranslation } from "react-i18next";
import { useQuery } from "@tanstack/react-query";
import { Link, useNavigate } from "react-router-dom";
import { EyeOff, Package, Plus, SearchX, Settings, X } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { EmptyState, EmptyStateAction } from "@/components/ui/EmptyState";
import { queryKeys } from "@/hooks/queries/keys";
import { productTemplatesApi } from "@/lib/api/productTemplates";

interface ItemsEmptyStateProps {
  hasFilters: boolean;
  searchTerm?: string;
  onClearSearch?: () => void;
  /** Widens the list back — the way out of a filter or chip that matched. */
  onClearFilters?: () => void;
  /** Rows the module filter keeps off the list; 0 until a probe says more. */
  hiddenCount?: number;
  /** Whether to offer the first product — the form asks for `items:write`. */
  canWrite?: boolean;
}

/**
 * A search that found nothing on the list. The list is of what is held, so a
 * product that exists only as a definition — one created inside a recipe or
 * a BOM — is not on it, and "no results" over a name the reader just made is
 * a false answer. The catalogue knows the name: when it has one, say so and
 * offer to put it in a location.
 */
function SearchEmptyState({
  searchTerm,
  onClearSearch,
  canWrite,
}: {
  searchTerm: string;
  onClearSearch: () => void;
  canWrite: boolean;
}) {
  const { t } = useTranslation("items");
  // The catalogue knowing a name does not mean the product has no stock: a
  // stocked row can be missing from the list only because a location or chip
  // narrowed it. So a match counts as "definition only" when the stock the
  // backend sums for it is nothing. The endpoint refuses a one-letter search.
  const lookupEnabled = searchTerm.length >= 2;
  const { data: definedMatch, isPending } = useQuery({
    queryKey: queryKeys.productTemplates.search(searchTerm),
    queryFn: async () => {
      const matches = await productTemplatesApi.search(searchTerm, 5);
      const stocks = await Promise.all(
        matches.map((m) => productTemplatesApi.getStock(m.id)),
      );
      return (
        matches.find((_, i) => Number(stocks[i].total_quantity) === 0) ?? null
      );
    },
    staleTime: 30_000,
    enabled: lookupEnabled,
  });

  // Until the lookup answers, "no results" would be the wrong answer shown
  // first.
  if (lookupEnabled && isPending) return null;

  if (definedMatch) {
    return (
      <EmptyState
        icon={Package}
        title={t("empty.definedMatchTitle", { name: definedMatch.name })}
        description={t("empty.definedMatchDescription")}
        primaryAction={
          canWrite ? (
            <Link
              to={`/inventory/items/add?name=${encodeURIComponent(definedMatch.name)}`}
            >
              <Button size="lg" leftIcon={<Plus size={20} />}>
                {t("addProduct")}
              </Button>
            </Link>
          ) : undefined
        }
      />
    );
  }
  return (
    <EmptyState
      icon={SearchX}
      title={t("empty.noSearchResultsTitle")}
      description={t("empty.noSearchResultsDescription", { term: searchTerm })}
      primaryAction={
        <Button size="lg" onClick={onClearSearch}>
          {t("empty.clearSearch")}
        </Button>
      }
    />
  );
}

/**
 * The three empties of the product list, told apart: a filter that found
 * nothing offers the way back, an organization without products yet is
 * offered its first one, and a list the module-data policy narrowed to zero
 * names the switch. Asking to add a product to a filter was the old single
 * answer to all three — over an account that had products.
 */
export default function ItemsEmptyState({
  hasFilters,
  searchTerm,
  onClearSearch,
  onClearFilters,
  hiddenCount = 0,
  canWrite = true,
}: ItemsEmptyStateProps) {
  const { t } = useTranslation("items");
  const navigate = useNavigate();
  // Any other narrowing — a chip, a picker, a module filter — owes the same
  // answer: nothing matches, and here is how to widen the list.
  const isFiltered = hasFilters;
  // Only an un-narrowed empty list may speak for the module filter: "no
  // results" for a search the reader typed is a different answer.
  const isHidden = !hasFilters && hiddenCount > 0;
  // The list is of what is held, so a product that so far exists only as a
  // definition — one created inside a recipe — is not on it. An empty list
  // over such products says where they are, instead of "no products" and an
  // invitation to add the first one.
  const { data: definedCount, isError: countFailed } = useQuery({
    queryKey: queryKeys.productTemplates.count,
    queryFn: productTemplatesApi.count,
    staleTime: 30_000,
    enabled: !hasFilters && !isHidden,
  });

  if (isHidden) {
    return (
      <EmptyState
        icon={EyeOff}
        title={t("hidden.title")}
        description={t("hidden.description")}
        primaryAction={
          <Button
            size="lg"
            onClick={() => navigate("/settings#module-data")}
            leftIcon={<Settings size={20} />}
          >
            {t("hidden.openSettings")}
          </Button>
        }
      />
    );
  }

  if (hasFilters && searchTerm && onClearSearch) {
    return (
      <SearchEmptyState
        searchTerm={searchTerm}
        onClearSearch={onClearSearch}
        canWrite={canWrite}
      />
    );
  }

  return (
    <EmptyState
      icon={isFiltered ? SearchX : Package}
      title={
        isFiltered
          ? t("empty.noSearchResultsTitle", {
              defaultValue: "No matching items",
            })
          : t("empty.title")
      }
      description={
        isFiltered
          ? t("empty.tryFilters")
          : !countFailed && (definedCount ?? 0) > 0
            ? t("empty.definedWithoutStock")
            : t("empty.addFirst")
      }
      primaryAction={
        isFiltered ? (
          onClearFilters ? (
            <EmptyStateAction
              label={t("empty.clearFilters", {
                defaultValue: "Clear filters",
              })}
              onClick={onClearFilters}
              leftIcon={X}
            />
          ) : undefined
        ) : canWrite ? (
          <Link to="/inventory/items/add">
            <Button size="lg" leftIcon={<Plus size={20} />}>
              {t("addProduct")}
            </Button>
          </Link>
        ) : undefined
      }
    />
  );
}
