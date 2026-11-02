import { memo, useState } from "react";
import { AlertTriangle, Link2, Trash2, X, Flame } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { InlinePopover } from "./InlinePopover";
import { Input } from "@/components/ui/Input";
import { ProductCombobox } from "@/components/ui/ProductCombobox";
import { UomSelect } from "@/modules/shared/components/UomSelect";
import { Checkbox } from "@/components/ui/Checkbox";
import { cn } from "@/lib/utils";
import { searchProductTemplates } from "@/lib/api/productTemplateOptions";
import type { Uom } from "@/types";
import {
  lacksUnit,
  willBeSpice,
  type DraftValue,
  type IngredientDraft,
} from "./importReviewUtils";
import { AllergenPicker } from "./AllergenPicker";
import { formatQuantityValue } from "@/utils/formatters";

interface ImportIngredientRowProps {
  ing: IngredientDraft;
  idx: number;
  showOriginal: boolean;
  flatUoms: Uom[];
  onUpdate: (
    key: number,
    field: keyof IngredientDraft,
    value: DraftValue,
  ) => void;
  onRemove: (key: number) => void;
  t: (key: string, options?: Record<string, unknown>) => string;
}

const ImportIngredientRow = memo(function ImportIngredientRow({
  ing,
  idx,
  showOriginal,
  flatUoms,
  onUpdate,
  onRemove,
  t,
}: ImportIngredientRowProps) {
  const unitUnrecognized = Boolean(ing.original_unit_text) && !ing.uom_id;
  const unitMissing = lacksUnit(ing);
  const [linkOpen, setLinkOpen] = useState(false);
  // A small amount files the line under spices whatever its mark says; the
  // row says so under itself and the chip points at that sentence.
  const spiceByAmount = willBeSpice(ing.metric_quantity, ing.uom_id, flatUoms);
  const spiceHintId = `import-spice-hint-${ing._key}`;

  const handleLinkSelect = (templateId: string, templateName: string) => {
    onUpdate(ing._key, "template_id", templateId);
    onUpdate(ing._key, "template_name", templateName);
    // The name is what reaches the database and what every downstream
    // lookup matches on, so the field and the chip beside it must not
    // disagree about what this ingredient is called.
    onUpdate(ing._key, "name", templateName);
    setLinkOpen(false);
  };
  return (
    <div className="rounded-xl border border-border bg-surface-card overflow-hidden">
      {showOriginal && ing.original_text && (
        <div className="bg-amber-50 border-b border-amber-100 px-3 py-1.5 text-xs text-on-warning italic">
          {ing.original_text}
        </div>
      )}

      <div className="flex items-center gap-2 px-3 pt-2.5 pb-1.5 border-b border-border">
        <span className="w-5 h-5 rounded-full bg-surface-raised flex items-center justify-center text-xs font-medium text-on-secondary shrink-0">
          {idx + 1}
        </span>
        <Input
          wrapperClassName="flex-1"
          type="text"
          aria-label={t("recipes:form.ingredient_name")}
          value={ing.name}
          onChange={(e) => onUpdate(ing._key, "name", e.target.value)}
          placeholder={t("recipes:form.ingredient_name")}
          className="text-sm bg-transparent outline-none placeholder:text-on-muted"
        />
        {ing.template_id ? (
          <span className="inline-flex items-center gap-1 text-xs text-on-success bg-success-50 rounded-full px-2 py-0.5 shrink-0">
            <Link2 size={10} />
            {ing.template_name ??
              t("recipes:import_export.review_template_matched")}
          </span>
        ) : (
          <span className="inline-flex items-center gap-1 text-xs text-on-secondary bg-surface-raised rounded-full px-2 py-0.5 shrink-0">
            {t("recipes:import_export.review_template_unmatched")}
          </span>
        )}
        <InlinePopover
          open={linkOpen}
          onOpenChange={setLinkOpen}
          className="w-64"
          trigger={
            <Button
              type="button"
              variant="ghost"
              size="iconSm"
              className="rounded text-xs text-primary-600 hover:bg-primary-50 hover:text-on shrink-0"
              aria-label={t("recipes:import_export.review_change_template")}
              title={t("recipes:import_export.review_change_template")}
            >
              <Link2 size={16} />
            </Button>
          }
        >
          <>
            <div className="flex items-center justify-between mb-1">
              <span className="text-xs font-medium text-on">
                {t("recipes:import_export.review_change_template")}
              </span>
              <Button
                type="button"
                variant="ghost"
                size="inline"
                onClick={() => setLinkOpen(false)}
                aria-label={t("common:a11y.close")}
                className="p-0.5 rounded text-on-muted hover:text-on-secondary"
              >
                <X size={16} />
              </Button>
            </div>
            <ProductCombobox
              value={null}
              onSelect={(product) =>
                handleLinkSelect(product.product_template_id, product.name)
              }
              search={searchProductTemplates}
              placeholder={t("recipes:import_export.review_template_search")}
              testId="import-template-search"
            />
          </>
        </InlinePopover>
        {/* ui-pattern: destructive-as-neutral — this row belongs to an
            import nobody has accepted yet, so removing it destroys no recipe
            and no ingredient */}
        <Button
          type="button"
          variant="ghost"
          size="iconSm"
          onClick={() => onRemove(ing._key)}
          aria-label={t("common:a11y.delete")}
          className="rounded text-on-muted hover:text-on-danger hover:bg-red-50"
        >
          <Trash2 size={16} />
        </Button>
      </div>

      <div className="flex items-center gap-2 px-3 py-2 flex-wrap">
        <Input
          wrapperClassName="w-20"
          type="number"
          aria-label={t("recipes:form.ingredient_quantity")}
          step="any"
          min={0}
          value={ing.quantity}
          onChange={(e) => onUpdate(ing._key, "quantity", e.target.value)}
          className="rounded-lg border border-border px-2 py-1.5 text-sm text-center focus:outline-none focus:ring-2 focus:ring-primary-300"
        />
        {ing.original_unit_text ? (
          <span className="inline-flex items-center gap-1.5">
            <span className="rounded-lg border border-primary-200 bg-primary-50 px-2.5 py-1.5 text-sm font-medium text-on">
              {ing.unit_display ?? ing.original_unit_text}
            </span>
            {unitUnrecognized && (
              <span
                className="inline-flex items-center gap-1 text-amber-600"
                title={t("recipes:import_export.unit_not_recognized")}
                data-testid="unit-not-recognized"
              >
                <AlertTriangle size={13} />
                <span className="text-xs font-medium whitespace-nowrap">
                  {t("recipes:import_export.review_unit_unrecognized_label")}
                </span>
              </span>
            )}
            {!unitUnrecognized && (
              <span className="text-xs text-on-muted whitespace-nowrap">
                (~{formatQuantityValue(ing.metric_quantity)}
                {(() => {
                  const sym = flatUoms.find((u) => u.id === ing.uom_id)?.symbol;
                  return sym ? ` ${sym}` : "";
                })()}
                )
              </span>
            )}
          </span>
        ) : null}
        {(!ing.original_unit_text || unitUnrecognized) && (
          <div className={cn("w-28", !unitMissing && "h-9")}>
            <UomSelect
              compact
              inline
              value={ing.uom_id}
              onChange={(id) => onUpdate(ing._key, "uom_id", id)}
              error={
                unitMissing
                  ? t("recipes:form.errors.ingredient_unit_required")
                  : undefined
              }
            />
          </div>
        )}
        <Checkbox
          checked={ing.is_optional}
          onChange={(e) => onUpdate(ing._key, "is_optional", e.target.checked)}
          className={cn(
            "h-3.5 w-3.5 rounded border-border",
            "text-primary-600 focus:ring-primary-500",
          )}
          label={
            <span className="text-xs text-on-secondary ml-auto">
              {t("recipes:form.ingredient_optional")}
            </span>
          }
        />
        {(() => {
          const autoSpice = spiceByAmount;
          const isSpice = autoSpice || ing.is_spice_forced;
          return (
            // A chip, not a checkbox like "Optional" beside it, and
            // deliberately so: this one shows a classification the import
            // already derived from the quantity, which the press overrides —
            // the row's other toggle is plain data the user is entering. Same
            // control shape as the tag chip in `RecipeCard`, so it carries the
            // same `aria-pressed`. On an amount-derived spice it is pressed
            // and disabled: the recipe screens count a small amount as a spice
            // whatever the stored mark says, so a press that appeared to clear
            // it would change nothing. Its explanation used to live in `title`,
            // which a touch screen never shows; it is now a line of help text
            // under this row, wired here through `aria-describedby`.
            <Button
              type="button"
              variant="ghost"
              size="contentSm"
              aria-pressed={isSpice}
              aria-describedby={autoSpice ? spiceHintId : undefined}
              disabled={autoSpice}
              onClick={() =>
                onUpdate(ing._key, "is_spice_forced", !ing.is_spice_forced)
              }
              className={cn(
                "px-2 py-0.5 text-xs rounded-full cursor-pointer",
                isSpice
                  ? "bg-amber-100 text-on-warning hover:bg-amber-200"
                  : "bg-surface-raised text-on-secondary hover:bg-surface-inset",
              )}
            >
              <Flame
                size={16}
                className="inline-block mr-1 text-amber-600 align-[-1px]"
              />
              {t("recipes:import_export.review_spice_label")}
            </Button>
          );
        })()}
        <AllergenPicker
          value={ing.allergens}
          onChange={(allergens) => onUpdate(ing._key, "allergens", allergens)}
        />
        {ing.group_name && (
          <span className="text-xs bg-surface-raised text-on-secondary px-2 py-0.5 rounded-full">
            {ing.group_name}
          </span>
        )}
      </div>
      {/* Under the line it explains: once above the whole list, the note
          read as a remark about the first line, whatever that was. */}
      {spiceByAmount && (
        <p id={spiceHintId} className="px-3 pb-2 text-xs text-on-muted">
          {t("recipes:import_export.review_spice_hint")}
        </p>
      )}
      {unitMissing && ing.unread_unit && (
        <p
          role="alert"
          className="px-3 pb-2 text-xs font-medium text-on-danger"
          data-testid="unit-unread"
        >
          {t("recipes:import_export.review_unit_unread", {
            unit: ing.unread_unit,
          })}
        </p>
      )}
    </div>
  );
});

export default ImportIngredientRow;
