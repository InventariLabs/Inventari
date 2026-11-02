import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { FlaskConical, Plus } from "lucide-react";
import { useLocation, useNavigate } from "react-router-dom";
import { useModulePageHeader } from "@/hooks/useModulePageHeader";
import { showListControls } from "@/hooks/useFilteredList";
import { useCanManage, useCanWrite } from "@/hooks/useCanWrite";
import { useLocalStorage } from "@/hooks/useLocalStorage";
import { Button } from "@/components/ui/Button";
import { EmptyState } from "@/components/ui/EmptyState";
import { ListControlBar } from "@/components/ui/ListControlBar";
import { Pagination } from "@/module-sdk";
import { QueryResult } from "@/components/ui/QueryResult";
import { useMakerRecipeCatalog } from "@/modules/maker/hooks/useRecipes";
import { MakerResultWidget } from "@/modules/maker/components/MakerResultWidget";
import { RecipeCard } from "@/modules/maker/components/RecipeCard";
import { RecipeTable } from "@/modules/maker/components/RecipeTable";
import { ProductionCreateSheet } from "@/modules/maker/components/ProductionCreateSheet";
import { RecipeCreateSheet } from "@/modules/maker/components/RecipeCreateSheet";
import type {
  RecipeCatalogItem,
  RecipeCatalogResponse,
  RecipeCatalogLocationState,
} from "@/modules/maker/types/maker";
import type { ProductOption } from "@/modules/maker/api/products";

const PAGE_LIMIT = 50;

/** Cards or rows — remembered, because a view switched on every visit is a
 *  preference the reader has to re-state instead of one they hold. */
const VIEW_STORAGE_KEY = "maker:catalog-view";

/** The three orderings the catalog endpoint understands. */
const SORTS = ["newest", "oldest", "name"] as const;
type Sort = (typeof SORTS)[number];

export default function RecipeCatalogPage() {
  const { t } = useTranslation("maker");
  const navigate = useNavigate();
  const location = useLocation();
  const { setHeader } = useModulePageHeader();
  // Writing a formula is the manager's side of the split the purpose card
  // promises: a BOM decides what production takes from stock. The floor
  // reads the catalog and produces from it.
  const canManage = useCanManage("maker");
  // Producing is the floor's write — a draft run, no stock moves until it is
  // completed. Without it the catalog is the read both views show.
  const canWrite = useCanWrite("maker");

  const [search, setSearch] = useState("");
  const [sort, setSort] = useState<Sort>("newest");
  const [skip, setSkip] = useState(0);
  const [viewMode, setViewMode] = useLocalStorage<"grid" | "list">(
    VIEW_STORAGE_KEY,
    "grid",
  );
  const [showCreateRecipe, setShowCreateRecipe] = useState(false);
  const [createFor, setCreateFor] = useState<ProductOption | null>(null);
  const [produceRecipe, setProduceRecipe] = useState<RecipeCatalogItem | null>(
    null,
  );

  const query = useMakerRecipeCatalog(
    search || undefined,
    sort,
    skip,
    PAGE_LIMIT,
  );
  // A page kept from before a failed refetch must not keep paging.
  const total = query.isError ? 0 : (query.data?.total ?? 0);
  const controlsVisible = showListControls({
    isLoading: query.isLoading,
    total,
    isNarrowed: search.trim().length > 0 || sort !== "newest",
  });

  useEffect(() => {
    setHeader({
      title: t("catalog.title"),
      subtitle: t("catalog.subtitle"),
      actions: (
        <div className="ml-auto flex gap-2">
          <Button
            onClick={() => navigate("/maker/production")}
            variant="outline"
          >
            {t("catalog.viewProduction")}
          </Button>
          {canManage && (
            <Button
              onClick={() => setShowCreateRecipe(true)}
              leftIcon={<Plus size={16} />}
            >
              {t("catalog.newRecipe")}
            </Button>
          )}
        </div>
      ),
    });
  }, [t, setHeader, navigate, canManage]);

  // Arriving from "this product has no formula yet" — open the create sheet
  // on the product we were sent, then drop the router state so Back or a
  // reload lands on a plain catalog instead of reopening the sheet. An
  // account that cannot manage formulas gets the plain catalog straight
  // away: the sheet's save would answer 403 after the form was filled.
  useEffect(() => {
    const state = location.state as RecipeCatalogLocationState | null;
    if (!state?.createRecipeFor) return;
    if (canManage) {
      setCreateFor(state.createRecipeFor);
      setShowCreateRecipe(true);
    }
    navigate(location.pathname, { replace: true, state: null });
  }, [location, navigate, canManage]);

  // One literal t() per key: a template literal hides all three from the
  // i18n scanner, which then reports them as orphans.
  const sortLabels: Record<Sort, string> = {
    newest: t("catalog.sort.newest"),
    oldest: t("catalog.sort.oldest"),
    name: t("catalog.sort.name"),
  };

  const newRecipeButton = canManage ? (
    <Button
      onClick={() => setShowCreateRecipe(true)}
      leftIcon={<Plus size={16} />}
    >
      {t("catalog.empty.cta")}
    </Button>
  ) : undefined;

  return (
    <div className="flex flex-col gap-6 animate-in fade-in slide-in-from-bottom-4 duration-500">
      {controlsVisible && (
        <ListControlBar
          search={{
            value: search,
            onChange: (value) => {
              setSearch(value);
              setSkip(0);
            },
            placeholder: t("catalog.searchPlaceholder"),
          }}
          // Search was the only tool on a catalog that can hold hundreds of
          // BOMs; the endpoint has always accepted these three orderings.
          secondaryFiltersLabel={t("catalog.sortLabel")}
          secondaryFilters={SORTS.map((key) => ({
            key,
            label: sortLabels[key],
            active: sort === key,
            onToggle: () => {
              setSort(key);
              setSkip(0);
            },
          }))}
          viewToggle={{ mode: viewMode, onChange: setViewMode }}
          resultCount={total > 0 ? total : undefined}
        />
      )}

      {/* The month's production result, the figure that used to sit on the
          inventory overview beside stock. Production's start is its home.
          On a phone it sits after the recipes: above them it filled the
          first screen and the first recipe started below the fold. */}
      <div className="order-last sm:order-none">
        <MakerResultWidget />
      </div>

      {/* Loading, error-with-retry and empty are the shared components now:
          the page used to hand-roll all three, and its error state was a
          single line of text with no way to try again. */}
      <QueryResult<RecipeCatalogResponse> query={query}>
        {(data) =>
          data.items.length === 0 ? (
            <EmptyState
              icon={FlaskConical}
              title={
                search ? t("catalog.noMatches.title") : t("catalog.empty.title")
              }
              description={
                search
                  ? t("catalog.noMatches.subtitle", { query: search })
                  : t("catalog.empty.subtitle")
              }
              primaryAction={search ? undefined : newRecipeButton}
            />
          ) : viewMode === "list" ? (
            <RecipeTable
              recipes={data.items}
              sort={sort}
              onProduce={canWrite ? (r) => setProduceRecipe(r) : undefined}
            />
          ) : (
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
              {data.items.map((recipe) => (
                <RecipeCard
                  key={recipe.id}
                  recipe={recipe}
                  onProduce={canWrite ? (r) => setProduceRecipe(r) : undefined}
                />
              ))}
            </div>
          )
        }
      </QueryResult>

      <Pagination
        skip={skip}
        limit={PAGE_LIMIT}
        total={total}
        onPrev={() => setSkip(Math.max(0, skip - PAGE_LIMIT))}
        onNext={() => setSkip(skip + PAGE_LIMIT)}
      />

      <RecipeCreateSheet
        open={showCreateRecipe}
        onClose={() => {
          setShowCreateRecipe(false);
          setCreateFor(null);
        }}
        preselectedProduct={createFor}
      />

      <ProductionCreateSheet
        open={produceRecipe !== null}
        onClose={() => setProduceRecipe(null)}
        onSuccess={(orderId) => {
          setProduceRecipe(null);
          navigate(`/maker/production/${orderId}`);
        }}
        preselectedProduct={
          produceRecipe
            ? {
                output_template_id: produceRecipe.output_template_id,
                name: produceRecipe.output_template_name ?? produceRecipe.name,
                recipe_id: produceRecipe.id,
              }
            : undefined
        }
      />
    </div>
  );
}
