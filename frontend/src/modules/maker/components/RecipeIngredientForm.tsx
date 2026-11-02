import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import axios from "axios";
import { ChevronDown, ChevronRight, Plus, X } from "lucide-react";
import { toast } from "sonner";
import { extractApiError } from "@/lib/errors";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { UomSelect } from "@/modules/shared/components/UomSelect";
import { ProductSearchInput } from "@/modules/maker/components/ProductSearchInput";
import { useAddBomLineToRecipe } from "@/modules/maker/hooks/useRecipes";
import { useFlatUoms } from "@/modules/shared/hooks/useUoms";
import type { ProductOption } from "@/modules/maker/api/products";

interface RecipeIngredientFormProps {
  recipeId: string;
  /**
   * The recipe's own output product. The search never offers it: the
   * server refuses a line that names the output as an ingredient, and the
   * id is known here before a single character is typed.
   */
  outputTemplateId: string;
}

/**
 * Add one ingredient to a recipe, in place on the composition tab.
 *
 * Writes through the per-recipe endpoint rather than the legacy
 * `/maker/bom` adapter, which always lands lines in the product's *default*
 * formula — wrong as soon as a product has a second one.
 */
export function RecipeIngredientForm({
  recipeId,
  outputTemplateId,
}: RecipeIngredientFormProps) {
  const { t } = useTranslation("maker");
  const { data: uoms = [], isError: unitsFailed } = useFlatUoms();
  const addLine = useAddBomLineToRecipe();

  const [child, setChild] = useState<ProductOption | null>(null);
  const [qty, setQty] = useState("1");
  const [uomId, setUomId] = useState("");
  // Yield loss and notes were only reachable from the legacy /maker/bom form,
  // so the main path could not set them at all. They stay folded away — most
  // lines need neither.
  const [showMore, setShowMore] = useState(false);
  const [yieldLoss, setYieldLoss] = useState("0");
  const [notes, setNotes] = useState("");
  // A refusal about this line belongs next to the line, not in a toast that
  // is gone four seconds later: the rules this endpoint enforces are about
  // the product that was picked, and the reader needs the sentence still on
  // screen while picking a different one.
  const [error, setError] = useState<string | null>(null);

  // Follow the picked product's own unit of measure — the common case is
  // "count this ingredient the way the ingredient is counted". A product the
  // catalogue has no unit for leaves the picker empty on purpose: the server
  // refuses a line whose unit cannot be read as the ingredient's stock unit,
  // so offering a unit nobody has chosen yet would be offering the refusal.
  useEffect(() => {
    setUomId(child?.uom_id ?? "");
  }, [child]);

  const selectedUom = uoms.find((u) => u.id === uomId);
  // The maker converts this quantity into the ingredient's stock unit, and
  // refuses a line in a unit it cannot convert. The picked product's unit is
  // the stock unit the catalogue declares, so the picker offers only what the
  // guard will accept instead of letting the refusal be the first word.
  const stockUomId = child?.uom_id ?? null;
  const stockSymbol = stockUomId
    ? (uoms.find((u) => u.id === stockUomId)?.symbol ?? "")
    : "";
  const parsedQty = Number(qty);
  const canSubmit =
    child !== null &&
    !Number.isNaN(parsedQty) &&
    parsedQty > 0 &&
    !!selectedUom &&
    !addLine.isPending;

  function handleAdd() {
    if (!child || !selectedUom) return;
    setError(null);
    addLine.mutate(
      {
        recipeId,
        data: {
          child_template_id: child.product_template_id,
          qty_per_batch: String(parsedQty),
          unit: selectedUom.symbol,
          uom_id: selectedUom.id,
          yield_loss_pct: yieldLoss.trim() || "0",
          notes: notes.trim() || null,
        },
      },
      {
        onSuccess: () => {
          setChild(null);
          setQty("1");
          setYieldLoss("0");
          setNotes("");
          setShowMore(false);
          setError(null);
          toast.success(t("composition.ingredientAdded"));
        },
        onError: (err) => {
          const duplicate =
            axios.isAxiosError(err) && err.response?.status === 409;
          setError(
            duplicate
              ? t("composition.errors.duplicateIngredient")
              : extractApiError(err, t("composition.errors.addIngredient")),
          );
        },
      },
    );
  }

  return (
    <div className="border-t border-border pt-3 space-y-3">
      <h4 className="text-xs uppercase tracking-widest text-on-muted font-medium">
        {t("composition.addIngredient")}
      </h4>
      <div className="flex flex-col sm:flex-row sm:items-end gap-2">
        <div className="flex-1 min-w-0">
          {child ? (
            <>
              <span className="text-xs font-medium uppercase text-on-secondary tracking-wide">
                {t("bom.childLabel")}
              </span>
              <div
                className="mt-1 flex items-center gap-2 rounded-lg border border-border bg-surface-card px-3 py-2 text-sm"
                data-testid="maker-composition-child-selected"
              >
                <span className="flex-1 min-w-0 truncate font-medium text-on">
                  {child.name}
                </span>
                <Button
                  type="button"
                  variant="ghost"
                  size="inline"
                  onClick={() => {
                    setChild(null);
                    setError(null);
                  }}
                  className="p-0 text-on-muted hover:text-on"
                  aria-label={t("bom.childClear")}
                  data-testid="maker-composition-child-clear"
                >
                  <X size={14} />
                </Button>
              </div>
            </>
          ) : (
            <ProductSearchInput
              label={t("bom.childLabel")}
              placeholder={t("bom.childPlaceholder")}
              testId="maker-composition-child-search"
              defaultUomId={uomId || undefined}
              excludeTemplateId={outputTemplateId}
              onSelect={(picked) => {
                setChild(picked);
                setError(null);
              }}
            />
          )}
        </div>
        <Input
          type="number"
          step="any"
          min="0"
          label={t("bom.qtyLabel")}
          value={qty}
          onChange={(e) => setQty(e.target.value)}
          wrapperClassName="sm:w-24 sm:shrink-0"
          data-testid="maker-composition-qty-input"
        />
        <div className="sm:w-32 sm:shrink-0">
          {/* No htmlFor: the picker is a button, not a field —
              same as every other labelled UomSelect in the app. */}
          <p className="block text-xs font-medium uppercase text-on-secondary tracking-wide">
            {t("bom.unitLabel")}
          </p>
          <div className="mt-1">
            <UomSelect
              compact
              inline
              value={uomId || null}
              onChange={(id) => setUomId(id)}
              convertibleTo={stockUomId}
              convertibleHint={
                stockUomId && !unitsFailed
                  ? t("bom.unitMustBeConvertible", { unit: stockSymbol })
                  : undefined
              }
            />
          </div>
        </div>
        <Button
          onClick={handleAdd}
          disabled={!canSubmit}
          leftIcon={<Plus size={16} />}
          className="shrink-0 whitespace-nowrap"
          data-testid="maker-composition-add-line"
        >
          {addLine.isPending ? t("bom.adding") : t("bom.add")}
        </Button>
      </div>

      {error && (
        <p
          role="alert"
          className="text-xs font-medium text-red-600"
          data-testid="maker-composition-error"
        >
          {error}
        </p>
      )}

      <div>
        {" "}
        <Button
          size="content"
          type="button"
          variant="ghost"
          onClick={() => setShowMore((v) => !v)}
          className="px-1 min-h-11 md:min-h-0 min-w-11 md:min-w-0 gap-1 text-xs uppercase tracking-widest text-on-muted font-medium hover:text-on hover:bg-transparent active:bg-transparent"
          aria-expanded={showMore}
          data-testid="maker-composition-more-toggle"
        >
          {showMore ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
          {t("composition.moreFields")}
        </Button>
        {showMore && (
          <div className="mt-2 space-y-2">
            <div className="flex flex-col sm:flex-row sm:items-end gap-2">
              <Input
                type="number"
                step="any"
                min="0"
                max="100"
                label={t("bom.yieldLabel")}
                value={yieldLoss}
                onChange={(e) => setYieldLoss(e.target.value)}
                wrapperClassName="sm:w-28 sm:shrink-0"
                aria-describedby="maker-composition-yield-hint"
                data-testid="maker-composition-yield-input"
              />
              <Input
                label={t("bom.notesLabel")}
                value={notes}
                onChange={(e) => setNotes(e.target.value)}
                placeholder={t("bom.notesPlaceholder")}
                wrapperClassName="flex-1 min-w-0"
                data-testid="maker-composition-notes-input"
              />
            </div>
            {/* The question this field does not answer is the one people bring
                to it: "how much did I actually lose?". That is measured after
                the fact, by entering what came out when the order is closed,
                and it is the main path — this number only reserves material so
                the plan adds up. Saying so is the whole fix; zero is a normal
                answer and nothing said it before. */}
            <p
              id="maker-composition-yield-hint"
              className="text-xs text-on-muted"
              data-testid="maker-composition-yield-hint"
            >
              {t("bom.yieldHint")}
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
