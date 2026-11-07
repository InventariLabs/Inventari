import { useState } from "react";
import { useTranslation } from "react-i18next";
import {
  Trash2,
  Flame,
  Pencil,
  Check,
  Coins,
  Link2,
  ChevronDown,
  ChevronUp,
} from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { UomSelect } from "@/modules/shared/components/UomSelect";
import {
  isCountedUom,
  useFlatUoms,
  useUoms,
} from "@/modules/shared/hooks/useUoms";
import type { IngredientStockUnit } from "@/modules/recipes/hooks/useIngredientStockUnits";
import { Checkbox } from "@/components/ui/Checkbox";
import { useOrganizationCurrency } from "@/hooks/useOrganizationCurrency";
import { formatMoney } from "@/utils/formatters";
import IngredientTemplateCombobox from "./IngredientTemplateCombobox";
import { AllergenPicker } from "./AllergenPicker";
import { ExclusionToggle } from "./ExclusionToggle";
import type { RecipeIngredientCreate } from "@/modules/recipes/types/core";
import type { Uom, UomCategory } from "@/types";
import type { TFunction } from "i18next";
import { unitLabel } from "@/lib/i18nHelpers";

export interface IngredientDraft extends Omit<
  RecipeIngredientCreate,
  "quantity" | "calories_kcal_per_100g" | "price" | "picking_skip"
> {
  _key: number;
  quantity: string;
  calories_kcal_per_100g: string;
  price: string;
  /** The row's tri-state exclusion: null leaves it to the server's heuristic. */
  picking_skip: boolean | null;
  // The wire keeps the unit's symbol optional-nullable, and so does the draft.
  uom_symbol?: string | null;
  allergens: string[];
}

/**
 * The units the narrowed picker offers, as the ids whose categories it keeps.
 *
 * The stock unit's own, and — for a counted stock unit (a piece or a bulk
 * package) whose card states a weight or volume per piece — the units of
 * that measure too, because that is what the maker bridges through to read
 * 100 g as a tenth of a pack. A measured stock unit has no such bridge.
 */
function pickerUnitIds(
  stockUnit: IngredientStockUnit | undefined,
  categories: UomCategory[],
): string[] | undefined {
  if (!stockUnit) return undefined;
  return isCountedUom(categories, stockUnit.uomId)
    ? [stockUnit.uomId, ...stockUnit.measureUomIds]
    : [stockUnit.uomId];
}

/**
 * What the narrowed unit picker says under itself.
 *
 * A picker narrowed to a counted unit — a piece or a bulk package — says
 * "only pcs" without a word about the way out: the product card's weight or
 * volume per piece, which is what puts ml on one scale with the stocked
 * piece or pack. Once the card carries it, the sentence says that the
 * measure's units are offered too. Every other narrowed picker keeps the
 * plain rule. Outside the component because the branch is about the
 * sentence, not about the row — and the row is at its lint complexity cap.
 */
function unitPickerHint(
  t: TFunction,
  stockUnit: IngredientStockUnit | undefined,
  uoms: Uom[],
  categories: UomCategory[],
  unitsFailed: boolean,
): string | undefined {
  // Without the catalogue the sentence would name the unit by its id, and
  // the picker under it already says the units did not load.
  if (!stockUnit || unitsFailed) return undefined;
  const symbol = unitLabel(
    t,
    uoms.find((u) => u.id === stockUnit.uomId)?.symbol ?? stockUnit.uomId,
  );
  if (!isCountedUom(categories, stockUnit.uomId))
    return t("form.unit_must_be_convertible", { unit: symbol });
  return stockUnit.measureUomIds.length
    ? t("form.unit_piece_with_measure", { unit: symbol })
    : t("form.unit_piece_no_measure", { unit: symbol });
}

interface RecipeIngredientRowProps {
  ing: IngredientDraft;
  idx: number;
  errors: Record<string, string>;
  onUpdate: (
    key: number,
    field: keyof IngredientDraft,
    value: IngredientDraft[keyof IngredientDraft],
  ) => void;
  onRemove: (key: number) => void;
  onNameBlur: (ing: IngredientDraft) => void;
  /**
   * The unit this linked ingredient is kept in (its product template's own),
   * with whether the card carries weight or volume per piece. The maker
   * converts the line's quantity into the stock unit, so the picker offers
   * only units that can be read as it — what the guard accepts, rather than
   * the refusal naming what it does not.
   */
  stockUnit?: IngredientStockUnit;
}

export default function RecipeIngredientRow({
  ing,
  idx,
  errors,
  onUpdate,
  onRemove,
  onNameBlur,
  stockUnit,
}: RecipeIngredientRowProps) {
  const { t, i18n } = useTranslation(["recipes", "common"]);
  const { data: uoms = [], isError: uomsFailed } = useFlatUoms();
  // The stock unit's category tells a counted unit from a kilogram, so the
  // hint can name the card's per-unit measure only where it would unlock a
  // unit.
  const { data: uomCategories = [], isError: categoriesFailed } = useUoms();
  const convertibleHint = unitPickerHint(
    t,
    stockUnit,
    uoms,
    uomCategories,
    uomsFailed || categoriesFailed,
  );
  const currency = useOrganizationCurrency();
  const lang = i18n.language?.substring(0, 2) ?? "en";
  const [kcalEditing, setKcalEditing] = useState<Set<number>>(new Set());
  const [priceEditing, setPriceEditing] = useState<Set<number>>(new Set());
  const [moreOptions, setMoreOptions] = useState<Set<number>>(new Set());

  const toggleMoreOptions = (key: number) =>
    setMoreOptions((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });

  const startKcalEdit = (key: number) =>
    setKcalEditing((prev) => new Set(prev).add(key));

  const stopKcalEdit = (key: number) =>
    setKcalEditing((prev) => {
      const next = new Set(prev);
      next.delete(key);
      return next;
    });

  const startPriceEdit = (key: number) =>
    setPriceEditing((prev) => new Set(prev).add(key));

  const stopPriceEdit = (key: number) =>
    setPriceEditing((prev) => {
      const next = new Set(prev);
      next.delete(key);
      return next;
    });

  return (
    <div className="rounded-xl border border-border bg-surface-card overflow-hidden">
      {/* Name row. The name keeps a floor and the chip and actions wrap
          under it on a phone — in one line they left it 72px at 390. */}
      <div className="flex flex-wrap items-center gap-2 px-3 pt-2.5 pb-1.5 border-b border-border">
        <span className="w-5 h-5 rounded-full bg-surface-raised text-on-secondary text-xs font-medium flex items-center justify-center shrink-0">
          {idx + 1}
        </span>
        <IngredientTemplateCombobox
          query={ing.name}
          value={ing.template_id ?? null}
          onChange={(templateId, templateName) => {
            onUpdate(ing._key, "template_id", templateId);
            // The name is a read key downstream, not a caption: nutrition
            // defaults, the shopping list and the shortage modal all match
            // on it. Linking used to keep whatever had been typed to find
            // the product, so one thing carried four names — "Mąk" on the
            // recipe, "Mąka pszenna typ 550" in the shortage modal.
            if (templateId) onUpdate(ing._key, "name", templateName);
          }}
          onQueryChange={(name) => onUpdate(ing._key, "name", name)}
          onBlur={() => onNameBlur(ing)}
          error={Boolean(errors[`ing_name_${idx}`])}
          className="flex-1 min-w-[14rem]"
        />
        {ing.template_id ? (
          <span
            className="inline-flex items-center gap-1 text-xs text-on-success bg-success-50 rounded-full px-2 py-0.5 shrink-0 mr-auto"
            title={t("form.ingredient_linked_tooltip")}
          >
            <Link2 size={10} />
            {t("form.ingredient_linked")}
          </span>
        ) : (
          <span
            className="inline-flex items-center gap-1 text-xs text-on-secondary bg-surface-raised rounded-full px-2 py-0.5 shrink-0 mr-auto"
            title={t("form.ingredient_unlinked_tooltip")}
          >
            <Link2 size={10} className="opacity-50" />
            {t("form.ingredient_unlinked")}
          </span>
        )}
        <Button
          size="content"
          type="button"
          variant="ghost"
          onClick={() => toggleMoreOptions(ing._key)}
          // 44x44 below `md`: the control is a 16px chevron beside fields the
          // same row carries, and a thumb landing next to it opens the row
          // instead. Above `md` the height stays the content's own and the
          // width returns to the label it shows beside the glyph.
          className="p-1 min-h-11 md:min-h-0 min-w-11 md:min-w-0 rounded-md text-xs gap-1 shrink-0 text-on-muted hover:text-on-secondary"
          aria-expanded={moreOptions.has(ing._key)}
          aria-label={t("form.ingredient_more_options")}
        >
          {moreOptions.has(ing._key) ? (
            <ChevronUp size={16} />
          ) : (
            <ChevronDown size={16} />
          )}
          <span className="hidden sm:inline">
            {t("form.ingredient_more_options")}
          </span>
        </Button>
        <Button
          type="button"
          variant="ghost"
          size="iconSm"
          onClick={() => onRemove(ing._key)}
          // 44x44 below `md`, like the chevron beside it.
          className="rounded-md text-on-muted hover:text-red-500 shrink-0 min-h-11 min-w-11 md:min-h-0 md:min-w-0"
          aria-label={t("form.remove_ingredient")}
        >
          <Trash2 size={16} />
        </Button>
      </div>

      {/* Qty + Unit row (always visible) */}
      <div className="flex items-center gap-2 px-3 py-2 flex-wrap">
        <Input
          type="number"
          min={0.01}
          step={0.01}
          // No visible label in the row — the column position carries the
          // meaning for the eye, the aria-label carries it into the tree.
          aria-label={t("form.ingredient_quantity")}
          value={ing.quantity}
          onChange={(e) => onUpdate(ing._key, "quantity", e.target.value)}
          // the shared Input wrapper is w-full by default — pin the
          // wrapper (not just the inner field) or the flex row wraps each
          // control onto its own line even with hundreds of px to spare.
          wrapperClassName="w-16 shrink-0"
          className={`w-full text-center py-1.5 px-1 ${errors[`ing_qty_${idx}`] ? "border-red-400 bg-red-50 text-on-danger" : ""}`}
        />
        <div className="w-28">
          <UomSelect
            compact
            inline
            value={ing.uom_id ?? null}
            onChange={(id, uom) => {
              onUpdate(ing._key, "uom_id", id);
              onUpdate(ing._key, "uom_symbol", uom.symbol);
            }}
            error={errors[`ing_uom_${idx}`]}
            convertibleTo={pickerUnitIds(stockUnit, uomCategories)}
          />
        </div>
        {/* Said at the full row width: inside the 7rem unit column the sentence
            wrapped to a ribbon of five words a line beside empty space. */}
        {convertibleHint && (
          <p
            className="basis-full text-xs text-on-muted"
            data-testid="uom-convertible-hint"
          >
            {convertibleHint}
          </p>
        )}
      </div>

      {/* More options (optional / kcal / price / always at home) */}
      {moreOptions.has(ing._key) && (
        <div className="flex items-center gap-3 px-3 pb-2.5 flex-wrap border-t border-border pt-2 mt-0">
          <Checkbox
            checked={ing.is_optional}
            onChange={(e) =>
              onUpdate(ing._key, "is_optional", e.target.checked)
            }
            label={
              <span className="text-xs text-on-secondary">
                {t("form.ingredient_optional")}
              </span>
            }
          />

          {/* Kcal per 100g */}
          <div className="flex items-center gap-1 shrink-0">
            <Flame size={11} className="text-amber-500 shrink-0" />
            {ing.calories_kcal_per_100g !== "" && !kcalEditing.has(ing._key) ? (
              <>
                <span className="text-xs text-on-secondary tabular-nums">
                  {ing.calories_kcal_per_100g} {t("form.kcal_per_100g")}
                </span>
                <Button
                  type="button"
                  variant="ghost"
                  size="inline"
                  onClick={() => startKcalEdit(ing._key)}
                  className="p-0.5 rounded text-on-muted hover:text-primary-500"
                  aria-label={t("form.edit_kcal")}
                >
                  <Pencil size={16} />
                </Button>
              </>
            ) : (
              <div className="flex items-center gap-1">
                <Input
                  type="number"
                  min={0}
                  step={1}
                  autoFocus={kcalEditing.has(ing._key)}
                  aria-label={t("form.kcal_per_100g")}
                  value={ing.calories_kcal_per_100g}
                  onFocus={() => startKcalEdit(ing._key)}
                  onChange={(e) =>
                    onUpdate(ing._key, "calories_kcal_per_100g", e.target.value)
                  }
                  onKeyDown={(e) => {
                    if (e.key === "Enter" || e.key === "Escape")
                      stopKcalEdit(ing._key);
                  }}
                  placeholder={t("form.kcal_placeholder")}
                  wrapperClassName="w-24 shrink-0"
                  className="w-full px-2 py-1.5 text-xs"
                />
                <span className="text-xs text-on-muted shrink-0">
                  {t("form.kcal_per_100g")}
                </span>
                {kcalEditing.has(ing._key) && (
                  <Button
                    type="button"
                    variant="ghost"
                    size="inline"
                    onClick={() => stopKcalEdit(ing._key)}
                    className="p-0.5 rounded text-primary-500 hover:text-primary-700"
                    aria-label={t("common:a11y.confirm")}
                  >
                    <Check size={16} />
                  </Button>
                )}
              </div>
            )}
          </div>

          {/* Price */}
          <div className="flex items-center gap-1 shrink-0">
            <Coins size={11} className="text-success-500 shrink-0" />
            {ing.price !== "" && !priceEditing.has(ing._key) ? (
              <>
                <span className="text-xs text-on-secondary tabular-nums">
                  {formatMoney(ing.price, currency, lang)}
                </span>
                <Button
                  type="button"
                  variant="ghost"
                  size="inline"
                  onClick={() => startPriceEdit(ing._key)}
                  className="p-0.5 rounded text-on-muted hover:text-primary-500"
                  aria-label={t("form.ingredient_price_label")}
                >
                  <Pencil size={16} />
                </Button>
              </>
            ) : (
              <div className="flex items-center gap-1">
                <Input
                  type="number"
                  min={0}
                  step={0.01}
                  autoFocus={priceEditing.has(ing._key)}
                  aria-label={t("form.ingredient_price_label")}
                  value={ing.price}
                  onFocus={() => startPriceEdit(ing._key)}
                  onChange={(e) => onUpdate(ing._key, "price", e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" || e.key === "Escape")
                      stopPriceEdit(ing._key);
                  }}
                  placeholder={t("form.ingredient_price_placeholder")}
                  wrapperClassName="w-20 shrink-0"
                  className="w-full px-2 py-1.5 text-xs"
                />
                <span className="text-xs text-on-muted shrink-0">
                  {ing.uom_symbol
                    ? t("form.ingredient_price_per", {
                        unit: unitLabel(t, ing.uom_symbol),
                      })
                    : t("form.ingredient_price_label")}
                </span>
                {priceEditing.has(ing._key) && (
                  <Button
                    type="button"
                    variant="ghost"
                    size="inline"
                    onClick={() => stopPriceEdit(ing._key)}
                    className="p-0.5 rounded text-primary-500 hover:text-primary-700"
                    aria-label={t("common:a11y.confirm")}
                  >
                    <Check size={16} />
                  </Button>
                )}
              </div>
            )}
          </div>

          <span className="ml-auto">
            <ExclusionToggle name={ing.name} templateId={ing.template_id} />
          </span>

          {/* Allergens (EU 1169/2011) */}
          <AllergenPicker
            value={ing.allergens ?? []}
            onChange={(allergens) => onUpdate(ing._key, "allergens", allergens)}
          />
        </div>
      )}

      {errors[`ing_name_${idx}`] && (
        <p className="text-xs text-red-500 px-3 pb-2">
          {errors[`ing_name_${idx}`]}
        </p>
      )}
    </div>
  );
}
