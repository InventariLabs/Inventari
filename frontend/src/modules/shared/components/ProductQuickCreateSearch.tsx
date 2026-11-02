import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Plus } from "lucide-react";
import { toast } from "sonner";
import { useQueryClient } from "@tanstack/react-query";
import { Button } from "@/components/ui/Button";
import { NativeSelect } from "@/components/ui/NativeSelect";
import {
  ProductCombobox,
  type ProductComboboxOption,
} from "@/components/ui/ProductCombobox";
import { extractApiError } from "@/lib/errors";
import { InlineQueryError } from "@/components/ui/QueryResult";
import { unitLabel } from "@/lib/i18nHelpers";
import { queryKeys } from "@/hooks/queries/keys";
import { useFlatUoms } from "@/modules/shared/hooks/useUoms";

/** The product name column's length; the create refuses anything longer. */
const PRODUCT_NAME_MAX_LENGTH = 255;

interface ProductQuickCreateSearchProps<T extends ProductComboboxOption> {
  /** Called with the picked product, or with the one just created. */
  onSelect: (product: T) => void;
  /** Server-side product search, called with the debounced query. */
  search: (query: string) => Promise<T[]>;
  /** Create a product from the typed name and the chosen unit. */
  createProduct: (name: string, uomId: string) => Promise<T>;
  label?: string;
  placeholder?: string;
  /** Prefix for `data-testid` on the input, the results and the create panel. */
  testId: string;
  /**
   * Unit of measure to seed the quick-create select with. Callers that
   * already hold a unit for the line pass it down, so the panel does not
   * re-ask for an answer that is on screen.
   */
  defaultUomId?: string | null;
  /** The same seed for a caller that knows the unit by its symbol only. */
  defaultUomSymbol?: string | null;
  /**
   * The unit is asked on the caller's own form, next to the quantity it
   * counts. The panel then creates the product in that unit and draws no
   * select of its own: a second unit picker inside the dropdown is a place a
   * reader never looks. `missingHint` says where to pick it while it is empty.
   */
  formUnit?: { uomId: string | null; missingHint: string };
  /** Name the search opens with — see `ProductCombobox`'s `initialQuery`. */
  initialQuery?: string;
  renderOptionMeta?: (product: T) => React.ReactNode;
}

/**
 * The shared `ProductCombobox` plus the one thing a search alone cannot do:
 * a search that matches nothing is a dead end unless the user can create the
 * product on the spot — the app has no "new product" screen, so creating one
 * from the typed name is offered here. It asks for a unit as well: a product
 * without one gives a module no measure for any quantity it later shows.
 *
 * Every module that lets a person pick a product and may meet an empty
 * catalogue wires this to its own search and its own create call; all
 * dropdown behaviour — portal, debounce, keyboard, ARIA — stays in the
 * combobox.
 */
export function ProductQuickCreateSearch<T extends ProductComboboxOption>({
  onSelect,
  search,
  createProduct,
  label,
  placeholder,
  testId,
  defaultUomId,
  defaultUomSymbol,
  formUnit,
  initialQuery,
  renderOptionMeta,
}: ProductQuickCreateSearchProps<T>) {
  const { t } = useTranslation("common");
  const queryClient = useQueryClient();
  const {
    data: uoms = [],
    isError: unitsFailed,
    error: unitsLoadError,
    refetch: refetchUnits,
  } = useFlatUoms();
  const defaultId =
    uoms.find(
      (u) =>
        (defaultUomId && u.id === defaultUomId) ||
        (!defaultUomId && defaultUomSymbol && u.symbol === defaultUomSymbol),
    )?.id ?? "";
  const [quickCreateUomId, setQuickCreateUomId] = useState(defaultId);
  const [creating, setCreating] = useState(false);
  // The default arrives with its hook data; a state seeded before the list
  // loaded would keep an empty select the caller did not mean.
  useEffect(() => {
    setQuickCreateUomId((current) => current || defaultId);
  }, [defaultId]);
  const createUomId = formUnit ? (formUnit.uomId ?? "") : quickCreateUomId;

  async function handleQuickCreate(
    query: string,
    select: (product: T) => void,
  ) {
    if (!query || creating || !createUomId) return;
    setCreating(true);
    try {
      const product = await createProduct(query, createUomId);
      // A first product changes "is the catalogue empty" for every screen
      // that gates on it (price lists, reorder rules); left alone they keep
      // saying "no products" until their cache expires.
      void queryClient.invalidateQueries({
        queryKey: queryKeys.productTemplates.count,
      });
      select(product);
    } catch (error) {
      // Keep the query so the user can retry or refine it.
      toast.error(extractApiError(error, t("productQuickCreate.error")));
    } finally {
      setCreating(false);
    }
  }

  return (
    <ProductCombobox
      value={null}
      onSelect={onSelect}
      search={search}
      label={label}
      placeholder={placeholder}
      testId={testId}
      initialQuery={initialQuery}
      maxLength={PRODUCT_NAME_MAX_LENGTH}
      renderOptionMeta={renderOptionMeta}
      renderNoResults={(query, select) => (
        <div className="p-3 space-y-2">
          <p className="text-xs text-on-muted">
            {t("productQuickCreate.noMatch", { query })}
          </p>
          {!formUnit && (
            <NativeSelect
              label={t("productQuickCreate.uom")}
              value={quickCreateUomId}
              onChange={(e) => setQuickCreateUomId(e.target.value)}
              data-testid={`${testId}-uom`}
            >
              <option value="">{t("productQuickCreate.uomPlaceholder")}</option>
              {uoms.map((uom) => (
                <option key={uom.id} value={uom.id}>
                  {unitLabel(t, uom.symbol)}
                </option>
              ))}
            </NativeSelect>
          )}
          {/* An empty list of units reads as a catalogue without any, and the
              product cannot be created without one. */}
          {unitsFailed && !formUnit && (
            <InlineQueryError
              error={unitsLoadError}
              onRetry={() => void refetchUnits()}
            />
          )}
          {/* A disabled button swallows the click silently (`pointer-events-none`),
              so the reason it waits lives here, told to the pointer and to screen
              readers alike. */}
          {!createUomId && (
            <p
              className="text-xs text-on-muted"
              data-testid={`${testId}-uom-required`}
              id={`${testId}-uom-required`}
            >
              {formUnit
                ? formUnit.missingHint
                : t("productQuickCreate.uomRequired")}
            </p>
          )}
          <Button
            size="content"
            type="button"
            variant="ghost"
            onClick={() => void handleQuickCreate(query, select)}
            disabled={creating || !createUomId}
            aria-describedby={
              !createUomId ? `${testId}-uom-required` : undefined
            }
            leftIcon={<Plus size={16} />}
            // Semantic accent tokens, not numbered shades: `accent` has no 950 in
            // tailwind.config.js, so the dark variants silently did not exist and
            // the button kept its light background in dark mode.
            className="w-full justify-start rounded-lg border border-dashed border-accent/40 bg-accent/10 px-3 py-2.5 text-left text-sm text-accent-700 hover:bg-accent/20 dark:text-accent-300"
            data-testid={`${testId}-create`}
          >
            {creating
              ? t("productQuickCreate.creating")
              : t("productQuickCreate.addAsNew", { name: query })}
          </Button>
        </div>
      )}
    />
  );
}
