import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import type { TFunction } from "i18next";
import { CheckCircle, Circle, Package, Trash2, Zap } from "lucide-react";
import type {
  ShoppingListItem,
  ShoppingNoteData,
} from "@/modules/shopping_lists/types/shopping";
import Button from "@/components/ui/Button";
import { useMoney } from "@/hooks/useMoney";
import { format, parseISO } from "date-fns";
import { dateFnsLocale, formatQuantityValue } from "@/utils/formatters";
import { useFlatUoms } from "@/modules/shared/hooks/useUoms";
import { unitLabel } from "@/lib/i18nHelpers";

interface ShoppingListItemCardProps {
  item: ShoppingListItem;
  currency?: string;
  onToggle: () => void;
  onDelete: () => void;
  /** Whether ticking the item off and removing it are offered. */
  canWrite?: boolean;
}

const priorityColors: Record<number, string> = {
  0: "border-transparent",
  1: "border-amber-400 bg-amber-50/30",
  2: "border-red-500/50 bg-red-50 shadow-md shadow-red-100/50",
};

/**
 * The service-composed note, re-told in the reader's language. The backend
 * froze the generation run's language into `notes`; the structured parts in
 * `note_data` let the card compose the same sentences now — including the
 * unit symbols, which go through `common:units` like everywhere else.
 */
/**
 * The recipe a line stored before the recipe travelled as data. Those lines
 * carry only the sentence, in the language of whoever pressed the button;
 * the five ways the server wrote it are known, so the recipe can be read
 * back out and re-told in the reader's language.
 */
const LEGACY_FOR_RECIPE =
  /^(?:For recipe|Do przepisu|Für Rezept|Pour la recette|Para la receta)\s*:\s(.+)$/;

function legacyRecipe(item: ShoppingListItem): string | null {
  if (item.source !== "recipe" || !item.notes) return null;
  return LEGACY_FOR_RECIPE.exec(item.notes)?.[1] ?? null;
}

function noteParts(
  item: ShoppingListItem,
  uomsById: Map<string, string>,
  unitsFailed: boolean,
  t: TFunction,
): string[] {
  const data = item.note_data as ShoppingNoteData | null | undefined;
  const oldRecipeNote = data ? null : legacyRecipe(item);
  if (oldRecipeNote) {
    return [t("shopping_lists:notes.forRecipe", { recipe: oldRecipeNote })];
  }
  // Composed here, the quantities would lose their units; the stored note
  // tells the same story in the language it was generated in.
  if (!data || unitsFailed) return item.notes ? [item.notes] : [];

  const parts: string[] = [];
  const unitLabel = (uomId: string | null | undefined) => {
    if (!uomId) return "";
    const symbol = uomsById.get(uomId);
    if (!symbol) return "";
    return t(`common:units.${symbol}`, { defaultValue: symbol });
  };

  if (data.needed_by) {
    parts.push(
      t("shopping_lists:notes.neededBy", {
        date: format(parseISO(data.needed_by), "P", {
          locale: dateFnsLocale(),
        }),
      }),
    );
  }
  const cs = data.check_stock;
  if (cs) {
    const available = [cs.available_qty, unitLabel(cs.available_uom_id)]
      .filter(Boolean)
      .join(" ");
    const required = [cs.required_qty, unitLabel(cs.required_uom_id)]
      .filter(Boolean)
      .join(" ");
    parts.push(t("shopping_lists:notes.checkStock", { available, required }));
  }
  if (data.for_recipe) {
    parts.push(
      t("shopping_lists:notes.forRecipe", { recipe: data.for_recipe }),
    );
  }
  if (data.matched_by_name) {
    parts.push(
      t("shopping_lists:notes.matchedByName", {
        product: data.matched_by_name,
      }),
    );
  }
  // None of the generated parts: `notes` is not their fallback but what the
  // reader wrote, and it stays beside the order reference.
  const generated =
    data.needed_by ||
    data.check_stock ||
    data.matched_by_name ||
    data.for_recipe;
  if (!generated && item.notes) parts.push(item.notes);
  if (data.converted_to_po) {
    parts.push(
      t("shopping_lists:notes.convertedToPo", {
        number: data.converted_to_po,
      }),
    );
  }
  return parts;
}

export function ShoppingListItemCard({
  item,
  currency,
  onToggle,
  onDelete,
  canWrite = true,
}: ShoppingListItemCardProps) {
  const { t } = useTranslation(["shopping_lists", "common"]);
  const money = useMoney();
  const { data: uoms = [], isError: unitsFailed } = useFlatUoms();
  const uomsById = useMemo(
    () => new Map(uoms.map((u) => [u.id, u.symbol])),
    [uoms],
  );
  // With structured parts the note is composed here, in the reader's
  // language; without them the composed fallback (`notes`) prints as-is.
  const parts = noteParts(item, uomsById, unitsFailed, t);

  return (
    <div
      className={`group relative bg-surface-card rounded-2xl shadow-sm border transition-all active:scale-[0.98] ${
        item.is_purchased
          ? "opacity-50 grayscale border-border"
          : `border-white hover:border-primary-100 ${priorityColors[item.priority] || "border-white"}`
      }`}
    >
      {item.priority === 2 && !item.is_purchased && (
        <div className="absolute -top-2 -right-2 bg-red-600 text-white p-1.5 rounded-lg shadow-lg z-10">
          <Zap size={14} fill="currentColor" />
        </div>
      )}
      <div className="flex items-center p-4 gap-4">
        {canWrite ? (
          <Button
            data-testid="purchase-checkbox"
            size="icon"
            variant={item.is_purchased ? "default" : "outline"}
            onClick={onToggle}
            aria-label={t("shopping_lists:detail.markPurchasedNamed", {
              name: item.name,
            })}
            aria-pressed={item.is_purchased}
            className={`shrink-0 rounded-full ${item.is_purchased ? "bg-accent-500" : ""}`}
          >
            {item.is_purchased ? (
              <CheckCircle size={24} />
            ) : (
              <Circle size={24} />
            )}
          </Button>
        ) : (
          /* Not a control any more, but still the answer to "is this one
             bought?" — the mark carries the state either way. */
          <span
            className="shrink-0 text-on-muted"
            aria-label={t("shopping_lists:detail.markPurchasedNamed", {
              name: item.name,
            })}
          >
            {item.is_purchased ? (
              <CheckCircle size={24} />
            ) : (
              <Circle size={24} />
            )}
          </span>
        )}
        <div
          className="flex-1 min-w-0"
          onClick={canWrite ? onToggle : undefined}
        >
          <div
            className={`font-semibold text-on truncate ${item.is_purchased ? "line-through opacity-50" : ""}`}
          >
            {item.name}
          </div>
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1 mt-1 text-[10px] font-medium text-on-muted uppercase tracking-tighter">
            {/* `normal-case` because a unit symbol is not a word: the row's
                uppercase turned "500 g" into "500 G", which is 500 giga-. */}
            {/* "—" for a line with no unit, not "pcs". An ingredient the
                recipe records without a measure reaches the list without one
                — the backend stopped borrowing the product's unit — and
                printing "pcs" here put back the unit that was removed one
                screen earlier. */}
            <span className="flex items-center gap-1 normal-case">
              <Package size={10} />
              {formatQuantityValue(item.quantity, item.uom?.rounding)}{" "}
              {unitLabel(t, item.uom?.symbol) || "—"}
            </span>
            {item.estimated_price && (
              <span className="text-primary-600 normal-case">
                ~{money(item.estimated_price, currency)}
              </span>
            )}
          </div>
        </div>
        {!item.is_purchased && canWrite && (
          <Button
            size="icon"
            variant="ghostDanger"
            onClick={(e) => {
              e.stopPropagation();
              onDelete();
            }}
            aria-label={t("common:a11y.deleteNamed", { name: item.name })}
          >
            <Trash2 size={18} />
          </Button>
        )}
      </div>
      {parts.length > 0 && !item.is_purchased && (
        <div className="mx-4 mb-4 p-2 bg-primary-50 rounded-xl text-[10px] text-primary-700 dark:text-primary-500 italic dark:bg-primary-500/10 border border-primary-100 dark:border-primary-500/20 leading-relaxed">
          {parts.join(" · ")}
        </div>
      )}
    </div>
  );
}
