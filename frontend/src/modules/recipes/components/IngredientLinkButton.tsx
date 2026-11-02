import { extractApiError } from "@/lib/errors";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Link2, X } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/Button";
import { ProductQuickCreateSearch } from "@/modules/shared/components/ProductQuickCreateSearch";
import { InlinePopover } from "./InlinePopover";
import {
  createProductTemplate,
  searchProductTemplates,
} from "@/lib/api/productTemplateOptions";
import { useLinkIngredientTemplate } from "../hooks/useRecipes";

interface Props {
  ingredientId: string;
  recipeId: string;
  /** The ingredient's own name: the search opens on it, and it is the name a
   *  product created from the dialog starts with. */
  ingredientName?: string;
  /** The ingredient's unit symbol, the unit that product starts with. */
  uomSymbol?: string | null;
  /** Full weight when linking is the only thing the row can offer, quiet
   *  weight when the row already says something useful on its own. */
  primary?: boolean;
  /** Fired after the link lands — the picking sheet re-reads its session. */
  onLinked?: () => void;
}

/**
 * Attach a recipe ingredient to a catalogue product by hand.
 *
 * Name matching answers most rows on its own, but not the ones where the
 * wording gives it nothing to go on ("Włoszczyzna" is a bundle of
 * vegetables, not a product). This is the way out of those, and lives in
 * its own component so the row it hangs off stays readable.
 *
 * The search itself is the shared product search: the hand-rolled one here
 * fired a request per keystroke, could answer a query with an older query's
 * results, and offered no keyboard at all. It also carries the way out of an
 * empty answer — creating the product on the spot — which matters most to
 * someone who starts from recipes, where the catalogue may hold nothing yet.
 * The search opens on the ingredient's name and the unit is the ingredient's,
 * and the product that comes back is linked like any picked one.
 */
export default function IngredientLinkButton({
  ingredientId,
  recipeId,
  ingredientName,
  uomSymbol,
  primary = false,
  onLinked,
}: Props) {
  const { t } = useTranslation("recipes");
  const [open, setOpen] = useState(false);
  const linkMutation = useLinkIngredientTemplate(recipeId);

  const handleSelect = async (templateId: string) => {
    setOpen(false);
    try {
      await linkMutation.mutateAsync({ ingredientId, templateId });
      toast.success(t("availability.linked_success"));
      onLinked?.();
    } catch (error) {
      toast.error(extractApiError(error, t("availability.link_failed")));
    }
  };

  return (
    <InlinePopover
      open={open}
      onOpenChange={setOpen}
      className="w-64"
      trigger={
        <Button
          type="button"
          variant="ghost"
          size="contentSm"
          className={`gap-1 rounded px-1 py-1 text-xs hover:bg-primary-50 shrink-0 ${
            primary ? "text-primary-600" : "text-on-muted"
          }`}
          aria-label={t("availability.link_to_product")}
          title={t("availability.link_to_product")}
        >
          <Link2 size={16} />
          {/* Icon-only below sm so the ingredient name keeps its width */}
          <span className="hidden sm:inline">
            {t("availability.link_to_product")}
          </span>
        </Button>
      }
    >
      <>
        <div className="flex items-center justify-between mb-1">
          <span className="text-xs font-medium text-on">
            {t("availability.link_to_product")}
          </span>
          <Button
            type="button"
            variant="ghost"
            size="inline"
            onClick={() => setOpen(false)}
            aria-label={t("common:a11y.close")}
            className="p-0.5 rounded text-on-muted hover:text-on-secondary"
          >
            <X size={16} />
          </Button>
        </div>
        <ProductQuickCreateSearch
          search={searchProductTemplates}
          createProduct={createProductTemplate}
          onSelect={(product) => void handleSelect(product.product_template_id)}
          placeholder={t("availability.link_search_placeholder")}
          testId="ingredient-link-search"
          initialQuery={ingredientName}
          defaultUomSymbol={uomSymbol}
        />
      </>
    </InlinePopover>
  );
}
