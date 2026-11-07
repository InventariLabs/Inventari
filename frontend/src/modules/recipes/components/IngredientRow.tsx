import { memo } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import { MapPin, GitMerge, Home } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/Button";
import { useCanWrite } from "@/hooks/useCanWrite";
import type { IngredientAvailability } from "@/modules/recipes/types/core";
import IngredientLinkButton from "./IngredientLinkButton";
import { ExclusionGate } from "./ExclusionGate";
import { fmtQty, isFractionalCountable } from "../utils";
import {
  useShoppingExclusions,
  useCreateShoppingExclusion,
  useDeleteShoppingExclusion,
} from "../hooks/useMealPlans";

import { formatDate } from "@/utils/helpers";
import { extractApiError } from "@/lib/errors";

interface Props {
  ingredient: IngredientAvailability;
  recipeId?: string;
}

// A dot rather than a <StatusBadge>: this row is one line in a dense ingredient
// list, where a text pill per row would outweigh the ingredient itself. The
// trade-off is that the dot carries its meaning in colour alone, so it is
// labelled for assistive technology instead of relying on `title`. Settled as
// the module's answer, not an oversight; `gray-300` is the neutral
// ramp step, remapped per theme like every other one here.
export const statusDot: Record<string, string> = {
  available: "bg-success-400",
  available_approx: "bg-amber-400",
  // Lighter than "missing": the goods are on the shelf, there is just
  // not enough of them — and the row now says how much.
  insufficient: "bg-red-300",
  missing: "bg-red-400",
  unknown: "bg-gray-300",
  // Stock whose measure cannot meet the recipe's is not a green dot: the two
  // numbers beside it are not on one scale, and nothing on the row said so.
  not_comparable: "bg-amber-400",
  // The availability status of the same condition, which the legend counts.
  incomparable: "bg-amber-400",
};

const statusLabel: Record<string, string> = {
  available: "availability.available",
  available_approx: "availability.available_approx",
  insufficient: "availability.insufficient",
  missing: "availability.missing",
  unknown: "availability.unknown",
  not_comparable: "availability.not_comparable_status",
};

const IngredientRow = memo(function IngredientRow({
  ingredient,
  recipeId,
}: Props) {
  const { t } = useTranslation("recipes");
  const showsBothReadings =
    !ingredient.quantities_comparable && ingredient.available_quantity != null;
  // What the dot stands for. "Found, but the measures cannot meet" is its own
  // answer and used to borrow the one for "found, and enough of it".
  const dotStatus = showsBothReadings ? "not_comparable" : ingredient.status;
  const dot = statusDot[dotStatus] ?? statusDot.unknown;
  const dotLabel = t(statusLabel[dotStatus] ?? statusLabel.unknown);
  // The backend rounds the requirement up to its unit's step, so a recipe
  // that asks for ½ pcs arrives as 1 pcs. Reading the raw number here keeps
  // the fractional hint alive for step-one units — with the rounded number
  // only, the piece branch of the check could never fire.
  const fractional = isFractionalCountable(
    ingredient.required_quantity_unrounded ?? ingredient.required_quantity,
    ingredient.required_uom,
  );
  // The step rounding is deliberate — part of a carton is a carton — but the
  // row showed only its result: the half the person had typed was nowhere on
  // the card, and 1 pcs looked like the save had changed the number. Say the
  // rounding, and only where the reader can see it: a scaled third keeps
  // formatting as ⅓ either way, so there is nothing to explain.
  const roundedFrom =
    ingredient.required_quantity_unrounded != null &&
    fmtQty(ingredient.required_quantity_unrounded) !==
      fmtQty(ingredient.required_quantity)
      ? ingredient.required_quantity_unrounded
      : null;
  // Both controls here write, and the API guards them with `recipes:write`:
  // linking an ingredient to a product and the "always at home" exclusion.
  // Offered to a reader, they ended in a 403 after the choice was made.
  const canWrite = useCanWrite("recipes");
  // Offered on an ingredient that points at no product, and only there. It
  // used to follow the stock answer instead, so "Link to product" sat on a
  // row whose product was linked and whose only trouble was that there was
  // not quite enough of it — a control that could change nothing.
  const canLink = canWrite && !ingredient.is_linked;
  const linkIsPrimary = ingredient.status === "unknown";

  const unitLabel = (uom: string | null | undefined) =>
    uom ? ` ${t(`common:units.${uom}`, { defaultValue: uom })}` : "";
  const measure = `${fmtQty(ingredient.required_quantity)}${unitLabel(
    ingredient.required_uom,
  )}`;
  const {
    data: exclusions = [],
    isError: exclusionsFailed,
    refetch: refetchExclusions,
  } = useShoppingExclusions();
  const createExclusion = useCreateShoppingExclusion();
  const deleteExclusion = useDeleteShoppingExclusion();

  function normalize(s: string): string {
    return s
      .trim()
      .toLowerCase()
      .normalize("NFD")
      .replace(/[\u0300-\u036f]/g, "")
      .split(/\s+/)
      .sort()
      .join(" ");
  }

  const normalizedName = normalize(ingredient.name);
  const matching = exclusions.find((e) => e.name_normalized === normalizedName);
  const isExcluded = !!matching;

  function handleToggleExclusion() {
    if (isExcluded && matching) {
      deleteExclusion.mutate(matching.id, {
        onSuccess: () => toast.success(t("meal_planner.exclusions_removed")),
        onError: (err) =>
          toast.error(extractApiError(err, t("meal_planner.exclusions_error"))),
      });
    } else {
      createExclusion.mutate(
        { name: ingredient.name },
        {
          onSuccess: () => toast.success(t("meal_planner.exclusions_added")),
          onError: (err: unknown) => {
            const status = (err as Error & { response?: { status?: number } })
              ?.response?.status;
            if (status === 409) {
              toast.info(t("meal_planner.exclusions_already_exists"));
            } else {
              toast.error(
                extractApiError(err, t("meal_planner.exclusions_error")),
              );
            }
          },
        },
      );
    }
  }

  const isShort =
    ingredient.status === "insufficient" &&
    ingredient.available_quantity != null;

  // Both readings, settled once — the wire keeps the available side
  // optional-nullable and the row says it twice at most.
  const availableReading = `${fmtQty(ingredient.available_quantity ?? 0)}${unitLabel(ingredient.available_uom)}`;
  const requiredReading = `${fmtQty(ingredient.required_quantity)}${unitLabel(ingredient.required_uom)}`;

  const renderMeta = () => {
    if (
      roundedFrom == null &&
      !ingredient.best_item?.location &&
      ingredient.match_type !== "fuzzy" &&
      !showsBothReadings &&
      !isShort &&
      ingredient.best_item?.fefo_days_left == null
    )
      return null;
    return (
      <div className="flex flex-wrap items-center gap-2 mt-0.5">
        {roundedFrom != null && (
          <span className="text-xs text-on-muted" data-testid="rounded-up">
            {t("availability.rounded_up", {
              from: `${fmtQty(roundedFrom)}${unitLabel(ingredient.required_uom)}`,
            })}
          </span>
        )}
        {isShort && (
          // How much is short, in words. The row used to say "Missing" and
          // nothing else, so 492 ml of the 500 ml wanted read as no milk.
          <span className="text-xs text-on-warning" data-testid="short-of">
            {t("availability.short_of", {
              available: availableReading,
              required: requiredReading,
            })}
          </span>
        )}
        {showsBothReadings && (
          // Said in words, not in a colour and a `title` — a hover explanation
          // reaches nobody holding a phone in a kitchen.
          <span
            className="text-xs text-on-warning"
            data-testid="not-comparable"
          >
            {t("availability.not_comparable", {
              available: availableReading,
              required: requiredReading,
            })}{" "}
            {ingredient.best_item ? (
              <Link
                to={`/inventory/items/${ingredient.best_item.item_id}`}
                className="underline underline-offset-2"
              >
                {t("availability.not_comparable_fix")}
              </Link>
            ) : (
              t("availability.not_comparable_hint")
            )}
          </span>
        )}
        {ingredient.best_item?.location && (
          <span className="flex items-center gap-0.5 text-xs text-on-muted">
            <MapPin size={9} />
            {ingredient.best_item.location}
          </span>
        )}
        {ingredient.match_type === "fuzzy" && (
          <span
            className="flex items-center gap-0.5 text-xs text-on-muted"
            title={t("availability.match_fuzzy")}
          >
            <GitMerge size={9} />
          </span>
        )}
        {ingredient.best_item?.expired && ingredient.best_item.expiry_date ? (
          // The pack is on the shelf and past its date. The row used to read
          // that date as "Short shelf life", a warning about a future the
          // chicken no longer had.
          <span className="text-xs text-on-danger" data-testid="expired">
            {t("availability.expired_since", {
              date: formatDate(ingredient.best_item.expiry_date),
            })}
          </span>
        ) : (
          ingredient.best_item?.fefo_days_left != null &&
          ingredient.best_item.expiry_date && (
            <span className="text-xs text-amber-500">
              {t("availability.fefo_expiry", {
                date: formatDate(ingredient.best_item.expiry_date),
              })}
            </span>
          )
        )}
      </div>
    );
  };

  return (
    <div className="flex items-center gap-3 py-2 border-b border-border last:border-0">
      {/* Stock status dot */}
      <span
        role="img"
        aria-label={dotLabel}
        className={`w-2 h-2 rounded-full shrink-0 ${dot}`}
        title={dotLabel}
      />

      {/* One reading for every ingredient: what it is, then how much of it.
          An ingredient added by hand used to get three fixed columns — the
          amount right-aligned, the unit, then the name — while an imported
          one read as a sentence, so a list holding both had a row in it that
          looked like a stray.

          The measure is parenthesised only for an imported line, where it is
          not the amount but a restatement of it: the recipe said "4 łyżki"
          in its own words and this is the same amount in a unit the app can
          count. Nothing restates an amount that was typed here. */}
      <div className="flex-1 min-w-0" data-testid="ingredient-name">
        <div className="truncate">
          <span className="text-sm text-on">
            {ingredient.display_text ?? ingredient.name}
          </span>
          <span
            className={`text-sm tabular-nums ${
              fractional ? "text-amber-600 font-medium" : "text-on-muted"
            }`}
            title={fractional ? t("availability.fractional_hint") : undefined}
          >
            {/* A real space rather than a margin: the row is one sentence,
                and it should still be one when it is copied out of the
                page. */}
            {` ${ingredient.display_text ? `(${measure})` : measure}`}
          </span>
        </div>
        {renderMeta()}
      </div>

      {/* Link-to-product — offered wherever the automatic answer may need
          correcting, quieter when the row already knows what to look for */}
      {canLink && recipeId && (
        <IngredientLinkButton
          ingredientId={ingredient.ingredient_id}
          recipeId={recipeId}
          ingredientName={ingredient.name}
          uomSymbol={ingredient.required_uom}
          primary={linkIsPrimary}
        />
      )}

      {/* Exclusion toggle */}
      {canWrite && (
        <ExclusionGate
          failed={exclusionsFailed}
          onRetry={() => void refetchExclusions()}
        >
          <Button
            type="button"
            variant="ghost"
            size="iconSm"
            onClick={handleToggleExclusion}
            className={`shrink-0 rounded ${
              isExcluded
                ? "text-on bg-primary-50 hover:bg-primary-50"
                : "text-on-muted/40 hover:text-primary-500 hover:bg-transparent"
            }`}
            aria-label={
              isExcluded
                ? t("meal_planner.exclusions_toggle_tooltip_remove")
                : t("meal_planner.exclusions_toggle_tooltip")
            }
            title={
              isExcluded
                ? t("meal_planner.exclusions_toggle_tooltip_remove")
                : t("meal_planner.exclusions_toggle_tooltip")
            }
          >
            <Home size={16} fill={isExcluded ? "currentColor" : "none"} />
          </Button>
        </ExclusionGate>
      )}
    </div>
  );
});

export default IngredientRow;
