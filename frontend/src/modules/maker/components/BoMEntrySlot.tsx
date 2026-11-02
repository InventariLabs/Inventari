import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import { ClipboardList } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { useBomSummary } from "@/modules/maker/hooks/useBom";
import type { ProductOption } from "@/modules/maker/api/products";
import type { RecipeCatalogLocationState } from "@/modules/maker/types/maker";
import type { Item } from "@/types";

interface BoMEntrySlotProps {
  data?: {
    item?: Item;
    requestLeave?: (go: () => void) => void;
  };
}

/** The product this item is an instance of, in the shape the create sheet wants. */
function toProductOption(item: Item, templateId: string): ProductOption {
  return {
    product_template_id: templateId,
    name: item.name,
    // The catalogue entry carries the SKU (a record of its own has none);
    // the nullable fields are settled for the create sheet's shape.
    sku: item.template?.sku ?? null,
    barcode: item.barcode ?? null,
    brand: item.brand ?? null,
    uom_id: item.uom_id ?? null,
    uom_symbol: item.uom?.symbol ?? null,
    image_url: item.image_url ?? null,
    is_stub: false,
  };
}

/**
 * Slot component for `item_edit_extra`. Renders a button linking to the
 * default recipe card for this item's product template
 * (`/maker/recipes/{default_recipe_id}`).
 *
 * When the product has no formula yet it sends the operator to the catalog
 * with the create sheet already pointed at this product — the button used to
 * link to `/maker/bom?parent=`, a screen that no longer exists, so the most
 * common case (a product without a formula, which is exactly when someone
 * reaches for this button) landed on a dead route.
 */
export function BoMEntrySlot({ data }: BoMEntrySlotProps) {
  const { t } = useTranslation("maker");
  const navigate = useNavigate();
  const item = data?.item;
  const templateId = item?.template_id;
  const { data: summary } = useBomSummary(templateId ?? undefined);
  if (!templateId || !item) return null;

  const entry = summary?.items.find((i) => i.template_id === templateId);
  const recipeId = entry?.default_recipe_id;
  const state: RecipeCatalogLocationState = {
    createRecipeFor: toProductOption(item, templateId),
  };

  // This is the one control in the item form that leaves the item form, and
  // as a plain link it took whatever had been typed with it. The host decides
  // whether that is worth a question.
  const go = () =>
    navigate(recipeId ? `/maker/recipes/${recipeId}` : "/maker", {
      state: recipeId ? undefined : state,
    });

  return (
    <div className="mt-3">
      <Button
        variant="outline"
        size="sm"
        type="button"
        data-testid="maker-bom-entry-link"
        onClick={() => (data?.requestLeave ? data.requestLeave(go) : go())}
      >
        <ClipboardList size={16} />
        {recipeId ? t("bomEntry.editRecipe") : t("bomEntry.createRecipe")}
      </Button>
    </div>
  );
}

export default BoMEntrySlot;
