import { useTranslation } from "react-i18next";
import { Link, useNavigate } from "react-router-dom";
import { EyeOff, Package, Plus, SearchX, Settings, X } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { EmptyState, EmptyStateAction } from "@/components/ui/EmptyState";

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
  const isPureSearch = hasFilters && !!searchTerm && !!onClearSearch;
  // Any other narrowing — a chip, a picker, a module filter — owes the same
  // answer: nothing matches, and here is how to widen the list.
  const isFiltered = hasFilters && !isPureSearch;
  // Only an un-narrowed empty list may speak for the module filter: "no
  // results" for a search the reader typed is a different answer.
  const isHidden = !hasFilters && hiddenCount > 0;

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

  return (
    <EmptyState
      icon={isPureSearch || isFiltered ? SearchX : Package}
      title={
        isPureSearch || isFiltered
          ? t("empty.noSearchResultsTitle", {
              defaultValue: "No matching items",
            })
          : t("empty.title")
      }
      description={
        isPureSearch
          ? t("empty.noSearchResultsDescription", {
              defaultValue: `No results for "{{term}}"`,
              term: searchTerm,
            })
          : isFiltered
            ? t("empty.tryFilters")
            : t("empty.addFirst")
      }
      primaryAction={
        isPureSearch ? (
          <Button size="lg" onClick={onClearSearch}>
            {t("empty.clearSearch", { defaultValue: "Clear search" })}
          </Button>
        ) : isFiltered ? (
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
