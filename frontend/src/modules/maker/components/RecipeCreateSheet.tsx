import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { extractApiError } from "@/lib/errors";
import { useNavigate } from "react-router-dom";
import { FlaskConical, Save } from "lucide-react";
import { toast } from "sonner";
import { Sheet } from "@/components/ui/Sheet";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { Card } from "@/components/ui/Card";
import { NativeSelect } from "@/components/ui/NativeSelect";
import { InlineQueryError } from "@/components/ui/QueryResult";
import { useFlatUoms } from "@/modules/shared/hooks/useUoms";
import { unitLabel } from "@/lib/i18nHelpers";
import { ProductSearchInput } from "@/modules/maker/components/ProductSearchInput";
import { useCreateMakerRecipe } from "@/modules/maker/hooks/useRecipes";
import type { ProductOption } from "@/modules/maker/api/products";
import { readableSku } from "@/lib/readableSku";

interface RecipeCreateSheetProps {
  open: boolean;
  onClose: () => void;
  onSuccess?: (recipeId: string) => void;
  /**
   * Output product to start from, skipping the search step. Set when the
   * sheet is opened for a product the operator already had on screen — the
   * "create a formula for this one" entry points on the item edit modal and
   * the items table.
   */
  preselectedProduct?: ProductOption | null;
}

/**
 * Bottom-sheet (mobile) / centered modal (desktop) for creating a formula.
 * Picks the output product via ProductSearchInput, then names the formula
 * and optionally says how much one batch makes, with the unit beside the
 * quantity. Navigates to the new formula's detail page on success.
 *
 * The unit used to be asked only inside the product search's "add as new"
 * panel, so a reader typing a new product met it hidden in a dropdown, and a
 * reader picking an existing one never saw what unit the yield was counted
 * in. It now stands next to the quantity: an existing product's own unit,
 * fixed, or the unit a product created here is made in.
 */
export function RecipeCreateSheet({
  open,
  onClose,
  onSuccess,
  preselectedProduct,
}: RecipeCreateSheetProps) {
  const { t } = useTranslation("maker");
  const navigate = useNavigate();

  const [selected, setSelected] = useState<ProductOption | null>(null);
  const [name, setName] = useState("");
  const [batchYield, setBatchYield] = useState("");
  const [uomId, setUomId] = useState("");

  const createMutation = useCreateMakerRecipe();
  const {
    data: uoms = [],
    isError: unitsFailed,
    error: unitsLoadError,
    refetch: refetchUnits,
  } = useFlatUoms();

  useEffect(() => {
    if (open) {
      // Opening for a known product: adopt it and default the name the same
      // way handleSelect does, so the operator only has to press Create.
      if (preselectedProduct) {
        setSelected(preselectedProduct);
        setName(preselectedProduct.name);
        setUomId(preselectedProduct.uom_id ?? "");
      }
      return;
    }
    setSelected(null);
    setName("");
    setBatchYield("");
    setUomId("");
  }, [open, preselectedProduct]);

  // A yield is counted in the output product's unit — production divides the
  // planned quantity by it without converting — so a product that has a unit
  // fixes the picker to it. Only a product without one lets the recipe say.
  const unitFixed = Boolean(selected?.uom_id);

  const canSubmit =
    selected !== null && name.trim().length > 0 && !createMutation.isPending;

  function handleSelect(product: ProductOption) {
    setSelected(product);
    // Default the formula name to the product name while the field is untouched.
    setName((prev) => (prev.trim() ? prev : product.name));
    if (product.uom_id) setUomId(product.uom_id);
  }

  function handleSubmit() {
    if (!selected) {
      toast.error(t("createRecipe.errors.productRequired"));
      return;
    }
    if (!name.trim()) {
      toast.error(t("createRecipe.errors.nameRequired"));
      return;
    }
    createMutation.mutate(
      {
        output_template_id: selected.product_template_id,
        name: name.trim(),
        batch_yield_qty: batchYield.trim() || undefined,
        batch_yield_uom_id: unitFixed ? undefined : uomId || undefined,
      },
      {
        onSuccess: (recipe) => {
          toast.success(t("createRecipe.success"));
          onClose();
          if (onSuccess) onSuccess(recipe.id);
          else navigate(`/maker/recipes/${recipe.id}`);
        },
        onError: (err) => {
          toast.error(extractApiError(err, t("createRecipe.errors.create")));
        },
      },
    );
  }

  return (
    <Sheet
      open={open}
      onClose={onClose}
      maxWidth="md"
      aria-label={t("createRecipe.title")}
    >
      <div className="px-6 pt-6 pb-4 border-b border-border">
        <div className="flex items-center gap-2 text-lg font-semibold text-on">
          <FlaskConical size={20} />
          {t("createRecipe.title")}
        </div>
        <p className="text-sm text-on-muted mt-1">
          {t("createRecipe.subtitle")}
        </p>
      </div>

      <div className="flex-1 overflow-y-auto p-6 space-y-5">
        {selected ? (
          <div className="space-y-2">
            <p className="block text-xs font-medium uppercase text-on-secondary tracking-wide">
              {t("create.productLabel")}
            </p>
            <Card className="p-3 flex items-center justify-between bg-accent-50 border-accent-100">
              <div className="min-w-0">
                <div className="font-medium truncate">{selected.name}</div>
                {readableSku(selected.sku) && (
                  <div className="text-xs text-on-muted font-mono">
                    {readableSku(selected.sku)}
                  </div>
                )}
              </div>
              <Button
                size="sm"
                variant="ghost"
                onClick={() => setSelected(null)}
                data-testid="maker-recipe-create-change-product"
              >
                {t("create.change")}
              </Button>
            </Card>
          </div>
        ) : (
          <ProductSearchInput
            onSelect={handleSelect}
            label={t("create.productLabel")}
            testId="maker-recipe-create-product"
            formUnit={{
              uomId: uomId || null,
              missingHint: t("createRecipe.unitFirst"),
            }}
          />
        )}

        <Input
          label={t("createRecipe.nameLabel")}
          placeholder={t("createRecipe.namePlaceholder")}
          value={name}
          onChange={(e) => setName(e.target.value)}
          data-testid="maker-recipe-create-name"
        />

        <div className="space-y-1.5">
          <div className="flex items-end gap-2">
            <Input
              type="number"
              step="any"
              min="0"
              label={t("createRecipe.batchYieldLabel")}
              placeholder="1"
              value={batchYield}
              onChange={(e) => setBatchYield(e.target.value)}
              wrapperClassName="flex-1 min-w-0"
              aria-describedby="maker-recipe-create-yield-hint"
              data-testid="maker-recipe-create-batch-yield"
            />
            <NativeSelect
              label={t("createRecipe.unitLabel")}
              value={uomId}
              onChange={(e) => setUomId(e.target.value)}
              disabled={unitFixed}
              wrapperClassName="w-32 shrink-0"
              data-testid="maker-recipe-create-unit"
            >
              <option value="">—</option>
              {uoms.map((uom) => (
                <option key={uom.id} value={uom.id}>
                  {unitLabel(t, uom.symbol)}
                </option>
              ))}
            </NativeSelect>
          </div>
          {/* An empty list of units reads as a catalogue without any. */}
          {unitsFailed && (
            <InlineQueryError
              error={unitsLoadError}
              onRetry={() => void refetchUnits()}
            />
          )}
          <p
            id="maker-recipe-create-yield-hint"
            className="text-xs text-on-muted"
          >
            {t("createRecipe.batchYieldHint")}
          </p>
        </div>
      </div>

      <div className="px-6 py-4 border-t border-border flex items-center justify-between gap-3">
        <Button variant="ghost" onClick={onClose}>
          {t("create.cancel")}
        </Button>
        <Button
          onClick={handleSubmit}
          disabled={!canSubmit}
          leftIcon={<Save size={16} />}
          data-testid="maker-recipe-create-submit"
        >
          {createMutation.isPending
            ? t("createRecipe.creating")
            : t("createRecipe.create")}
        </Button>
      </div>
    </Sheet>
  );
}
