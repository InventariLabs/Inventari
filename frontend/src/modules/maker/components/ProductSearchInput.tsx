import { useTranslation } from "react-i18next";
import { ClipboardList } from "lucide-react";
import { ProductQuickCreateSearch } from "@/modules/shared/components/ProductQuickCreateSearch";
import {
  makerProductsApi,
  type ProductOption,
} from "@/modules/maker/api/products";
import { useTemplateIdsWithBom } from "@/modules/maker/hooks/useBom";
import { InlineQueryError } from "@/components/ui/QueryResult";

interface ProductSearchInputProps {
  /** Called when the user selects a product from the dropdown. */
  onSelect: (product: ProductOption) => void;
  /** Accessibility label shown above the input. */
  label?: string;
  /** Placeholder for the search input. */
  placeholder?: string;
  /** Test id prefix for the input + result buttons. */
  testId?: string;
  /**
   * Unit of measure to seed the quick-create select with. Callers that
   * already hold a unit for the line (the recipe ingredient form) pass it
   * down, so the panel does not re-ask for an answer that is on screen.
   */
  defaultUomId?: string | null;
  /** See `ProductQuickCreateSearch`: the caller asks the unit itself. */
  formUnit?: { uomId: string | null; missingHint: string };
  /**
   * A product the picked one cannot be: the composition form passes the
   * recipe's own output product, which the server refuses as a self-reference
   * — offering it invited a 400 the search could have prevented.
   */
  excludeTemplateId?: string | null;
  /**
   * Mark each result that already has a formula. The output search turns
   * this on: picking a product with no formula is how a reader lands on the
   * "no recipe" dead end four screens later, and the marker says so before
   * the pick, not after.
   */
  formulaBadge?: boolean;
}

/**
 * The maker module's product search: the shared quick-create search wired to
 * the maker's own search endpoint and create call, plus the two things only
 * this module marks or filters — products that already have a formula, and the
 * recipe's own output.
 *
 * All dropdown behaviour — portal, debounce, keyboard, ARIA — lives in the
 * shared combobox, and the create-on-the-spot panel in the shared search.
 */
export function ProductSearchInput({
  onSelect,
  label,
  placeholder,
  testId = "maker-product-search",
  defaultUomId,
  formUnit,
  excludeTemplateId,
  formulaBadge = false,
}: ProductSearchInputProps) {
  const { t } = useTranslation("maker");
  const {
    data: formulaTemplateIds,
    isError: formulasFailed,
    error: formulasError,
    refetch: refetchFormulas,
  } = useTemplateIdsWithBom(formulaBadge);
  const formulaIds = new Set(formulaTemplateIds ?? []);

  return (
    <div className="space-y-1.5">
      <ProductQuickCreateSearch
        onSelect={onSelect}
        search={async (query) => {
          const products = await makerProductsApi.search(query, 10);
          return excludeTemplateId
            ? products.filter(
                (product) => product.product_template_id !== excludeTemplateId,
              )
            : products;
        }}
        createProduct={makerProductsApi.create}
        label={label}
        placeholder={placeholder ?? t("create.searchPlaceholder")}
        testId={testId}
        defaultUomId={defaultUomId}
        formUnit={formUnit}
        renderOptionMeta={
          formulaBadge
            ? (product) =>
                formulaIds.has(product.product_template_id) ? (
                  <span
                    className="inline-flex items-center text-accent-700"
                    aria-label={t("create.hasBom")}
                    data-testid={`${testId}-has-formula`}
                  >
                    <ClipboardList size={14} />
                  </span>
                ) : null
            : undefined
        }
      />
      {/* A product without its formula badge reads as a product without a
        formula, which is the cue to write a second one. */}
      {formulasFailed && (
        <InlineQueryError
          error={formulasError}
          onRetry={() => void refetchFormulas()}
        />
      )}
    </div>
  );
}
