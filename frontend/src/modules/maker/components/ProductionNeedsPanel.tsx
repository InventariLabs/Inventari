import { useTranslation } from "react-i18next";
import type { TFunction } from "i18next";
import { AlertTriangle, CheckCircle2, ShoppingCart } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { useMoney } from "@/hooks/useMoney";
import { useCanWrite } from "@/hooks/useCanWrite";
import { useModules } from "@/contexts/ModulesContext";
import { extractApiError } from "@/lib/errors";
import { formatQuantityLocalized, unitLabel } from "@/lib/i18nHelpers";
import { CostGapNote } from "@/modules/maker/components/CostFigure";
import { EmptyBomNotice } from "@/modules/maker/components/EmptyBomNotice";
import { MissingRecipeNotice } from "@/modules/maker/components/MissingRecipeNotice";
import { useAddShortagesToShoppingList } from "@/modules/maker/hooks/useProduction";
import { useMakerSettings } from "@/modules/maker/hooks/useRecipes";
import type { ProductOption } from "@/modules/maker/api/products";
import type {
  ProductionMode,
  ProductionOrderCreateInput,
  ProductionPreviewResponse,
} from "@/modules/maker/types/maker";

interface ProductionNeedsPanelProps {
  mode: ProductionMode;
  /** The run the form describes, or null while it does not name one yet. */
  payload: ProductionOrderCreateInput | null;
  preview: ProductionPreviewResponse | undefined;
  isLoading: boolean;
  error: Error | null;
  outputProduct: ProductOption | null;
}

type Ingredient = NonNullable<ProductionPreviewResponse["ingredients"]>[number];

function isShort(ingredient: Ingredient): boolean {
  return ingredient.shortage == null || Number(ingredient.shortage) > 0;
}

/**
 * What the run takes off stock (or will need), before anything is saved.
 *
 * The shortage used to surface only at "Create draft", and a run already made
 * was then refused at completion. Each ingredient says what it needs against
 * what the records hold where the run draws; under the list, the cost per
 * unit and what is left of the reference price, and what saving will do
 * about a shortfall — count it when the goods were already used, buy it when
 * the run is a plan.
 */
export function ProductionNeedsPanel({
  mode,
  payload,
  preview,
  isLoading,
  error,
  outputProduct,
}: ProductionNeedsPanelProps) {
  const { t } = useTranslation("maker");

  if (payload === null) {
    return (
      <p className="text-sm text-on-secondary">{t("create.needs.pick")}</p>
    );
  }
  if (error) {
    return (
      <p className="text-sm text-on-danger" role="alert">
        {extractApiError(error, t("preview.loadFailed"))}
      </p>
    );
  }
  if (!preview) {
    return isLoading ? (
      <p className="text-sm text-on-secondary">{t("create.needs.loading")}</p>
    ) : null;
  }
  if (preview.recipe_state === "no_recipe") {
    return <MissingRecipeNotice product={outputProduct} />;
  }
  const ingredients = preview.ingredients ?? [];
  if (ingredients.length === 0) {
    return <EmptyBomNotice recipeId={preview.recipe_id} />;
  }

  return (
    <div className="space-y-4" aria-busy={isLoading}>
      <h3 className="text-sm font-semibold text-on">
        {mode === "made"
          ? t("create.needs.headingMade")
          : t("create.needs.headingPlanned")}
      </h3>
      <ul className="divide-y divide-border">
        {ingredients.map((ingredient) => (
          <IngredientRow
            key={ingredient.child_template_id}
            ingredient={ingredient}
          />
        ))}
      </ul>
      <CostLine preview={preview} />
      <ShortageNote mode={mode} preview={preview} payload={payload} />
    </div>
  );
}

function IngredientRow({ ingredient }: { ingredient: Ingredient }) {
  const { t } = useTranslation("maker");
  const have = formatQuantityLocalized(
    t,
    ingredient.available,
    ingredient.convertible
      ? ingredient.uom_symbol
      : ingredient.available_uom_symbol,
  );
  let status: string;
  if (ingredient.shortage == null) {
    status = t("create.needs.unknown", { have });
  } else if (Number(ingredient.shortage) > 0) {
    status = t("create.needs.short", {
      have,
      short: formatQuantityLocalized(
        t,
        ingredient.shortage,
        ingredient.uom_symbol,
      ),
    });
  } else {
    status = t("create.needs.have", { have });
  }
  return (
    <li className="py-2 flex items-start justify-between gap-3 text-sm">
      <div className="min-w-0">
        <div className="text-on break-words">
          {ingredient.child_template_name ?? t("create.needs.unnamed")}
        </div>
        <div
          className={
            isShort(ingredient)
              ? "text-xs text-on-warning"
              : "text-xs text-on-secondary"
          }
        >
          {status}
        </div>
      </div>
      <div className="text-on font-medium shrink-0 tabular-nums">
        {formatQuantityLocalized(t, ingredient.needed, ingredient.uom_symbol)}
      </div>
    </li>
  );
}

/** What the result per unit means against the reference price: a sale price
 *  for a margin, the shop's price for savings. */
function referenceSentence(
  t: TFunction<"maker">,
  savings: boolean,
  result: number,
  values: { price: string; result: string; unit: string },
): string {
  if (result >= 0) {
    return savings
      ? t("create.needs.savingsLeft", values)
      : t("create.needs.marginLeft", values);
  }
  return savings
    ? t("create.needs.savingsLost", values)
    : t("create.needs.marginLost", values);
}

function CostLine({ preview }: { preview: ProductionPreviewResponse }) {
  const { t } = useTranslation("maker");
  const money = useMoney();
  // The reference price is a sale price for a margin and a shop price for
  // savings ("Shop price minus the cost to make it"): a savings organization
  // was told it sells at the shop's price. Margin until the server says.
  const { data: settings } = useMakerSettings();
  const savings = settings?.reference_direction === "SAVINGS";
  // An ingredient nobody can price adds nothing, so the figure is a floor:
  // the sentence the cost preview carries says so here too.
  const unpriced = preview.missing_cost_lines.length;
  const priced = preview.entries.length - unpriced;
  if (preview.unit_cost == null)
    return <CostGapNote priced={priced} unpriced={unpriced} />;
  const unit = preview.planned_uom_symbol
    ? unitLabel(t, preview.planned_uom_symbol)
    : t("create.needs.unitFallback");
  const result =
    preview.result_per_unit == null ? null : Number(preview.result_per_unit);
  return (
    <Card className="p-3 bg-surface-raised text-sm space-y-1">
      <p className="text-on">
        {t("create.needs.cost", {
          unitCost: money(preview.unit_cost),
          unit,
          total: money(
            Number(preview.unit_cost) * Number(preview.planned_qty || 0),
          ),
        })}
      </p>
      <CostGapNote priced={priced} unpriced={unpriced} />
      {preview.reference_price != null && result != null && (
        <p className="text-on-secondary">
          {referenceSentence(t, savings, result, {
            price: money(preview.reference_price),
            result: money(Math.abs(result)),
            unit,
          })}
        </p>
      )}
    </Card>
  );
}

function ShortageNote({
  mode,
  preview,
  payload,
}: {
  mode: ProductionMode;
  preview: ProductionPreviewResponse;
  payload: ProductionOrderCreateInput;
}) {
  const { t } = useTranslation("maker");
  const short = (preview.ingredients ?? []).filter(isShort);
  if (short.length === 0) {
    return (
      <p className="text-sm text-on-success flex items-center gap-2">
        <CheckCircle2 size={16} className="shrink-0" />
        {t("create.needs.enough")}
      </p>
    );
  }
  const unmeasurable = short.some((ingredient) => ingredient.shortage == null);
  let sentence: string;
  if (unmeasurable) sentence = t("create.needs.unmeasurable");
  else if (mode === "made") sentence = t("create.needs.shortMade");
  else sentence = t("create.needs.shortPlanned");
  return (
    <Card className="p-3 bg-amber-50 text-on-warning text-sm space-y-2">
      <p className="flex items-start gap-2">
        <AlertTriangle size={16} className="mt-0.5 shrink-0" />
        <span>{sentence}</span>
      </p>
      {mode === "planned" && !unmeasurable && (
        <AddShortfallButton short={short} payload={payload} />
      )}
    </Card>
  );
}

function AddShortfallButton({
  short,
  payload,
}: {
  short: Ingredient[];
  payload: ProductionOrderCreateInput;
}) {
  const { t } = useTranslation("maker");
  const { isModuleEnabled } = useModules();
  const canWrite = useCanWrite("shopping_lists");
  const mutation = useAddShortagesToShoppingList();
  if (!isModuleEnabled("shopping_lists") || !canWrite) return null;
  const label =
    short.length === 1
      ? t("create.needs.addOne", {
          quantity: formatQuantityLocalized(
            t,
            short[0].shortage,
            short[0].uom_symbol,
          ),
          name: short[0].child_template_name ?? "",
        })
      : t("create.needs.addAll");
  return (
    <Button
      variant="outline"
      size="sm"
      leftIcon={<ShoppingCart size={16} />}
      isLoading={mutation.isPending}
      onClick={() =>
        mutation.mutate(payload, {
          onSuccess: (result) =>
            toast.success(
              result.added_count > 0
                ? t("create.needs.added", { name: result.list_name ?? "" })
                : t("create.needs.alreadyListed"),
            ),
          onError: (err) =>
            toast.error(extractApiError(err, t("create.needs.addFailed"))),
        })
      }
      data-testid="maker-create-add-shortfall"
    >
      {label}
    </Button>
  );
}
