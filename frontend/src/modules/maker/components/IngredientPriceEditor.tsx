import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Check, Pencil, X } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { extractApiError } from "@/lib/errors";
import { formatMoney } from "@/utils/formatters";
import { useOrganizationCurrency } from "@/hooks/useOrganizationCurrency";
import { useSetIngredientPrice } from "@/modules/maker/hooks/useRecipes";

interface IngredientPriceEditorProps {
  templateId: string;
  /** The unit the price is per, as the line states it. */
  unit: string;
  price: string | null;
  canManage: boolean;
}

/**
 * The price typed once on a product the records do not price.
 *
 * An ingredient made an hour ago has no cost layer and no supplier quote, so
 * the formula's cost reads as zero and its margin says nothing — the first
 * question a craft producer asks. The price is the product's, not the line's:
 * two formulas that share the ingredient share what it costs, so it is saved
 * against the product rather than the formula on screen.
 */
export function IngredientPriceEditor({
  templateId,
  unit,
  price,
  canManage,
}: IngredientPriceEditorProps) {
  const { t, i18n } = useTranslation("maker");
  const currency = useOrganizationCurrency();
  const setPrice = useSetIngredientPrice();
  const [draft, setDraft] = useState<string | null>(null);

  const hasPrice = price !== null && price !== "" && Number(price) >= 0;

  async function save() {
    if (draft === null) return;
    const value = draft.trim();
    if (value !== "" && Number.isNaN(Number(value))) return;
    try {
      await setPrice.mutateAsync({
        templateId,
        unitPrice: value === "" ? null : value,
      });
      setDraft(null);
      toast.success(t("composition.priceSaved"));
    } catch (err) {
      toast.error(extractApiError(err, t("composition.priceSaveFailed")));
    }
  }

  if (draft !== null) {
    return (
      <span className="inline-flex items-center gap-1">
        <Input
          wrapperClassName="w-20"
          type="number"
          min="0"
          step="0.01"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          className="h-7 text-xs"
          aria-label={t("composition.typedPrice")}
          data-testid="maker-ingredient-price-input"
        />
        <span className="text-xs text-on-muted">/ {unit}</span>
        <Button
          size="sm"
          variant="ghost"
          onClick={() => void save()}
          disabled={setPrice.isPending}
          aria-label={t("common:actions.save")}
          data-testid="maker-ingredient-price-save"
        >
          <Check size={14} className="text-accent-600" />
        </Button>
        <Button
          size="sm"
          variant="ghost"
          onClick={() => setDraft(null)}
          aria-label={t("common:actions.cancel")}
        >
          <X size={14} />
        </Button>
      </span>
    );
  }

  return (
    <span className="inline-flex items-center gap-1 text-xs">
      {hasPrice ? (
        <span
          className="tabular-nums text-on-secondary"
          data-testid="maker-ingredient-typed-price"
        >
          {t("composition.typedPrice")}:{" "}
          {formatMoney(price, currency, i18n.language)} / {unit}
        </span>
      ) : null}
      {canManage && (
        <Button
          size="sm"
          variant="ghost"
          onClick={() => setDraft(price ?? "")}
          className="text-on-muted"
          aria-label={
            hasPrice ? t("composition.editPrice") : t("composition.setPrice")
          }
          title={t("composition.typedPriceHint")}
          data-testid="maker-ingredient-price-edit"
        >
          <Pencil size={12} />
          <span className="ml-1">
            {hasPrice ? t("composition.editPrice") : t("composition.setPrice")}
          </span>
        </Button>
      )}
    </span>
  );
}
