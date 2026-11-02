import { memo } from "react";
import {
  CheckCircle2,
  Package,
  Clock,
  ChevronRight,
  AlertTriangle,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import { Badge } from "@/components/ui/Badge";
import type { PickingItem } from "@/modules/recipes/types/core";
import type { PickingRefusal } from "../hooks/usePickingSession";
import { fmtQty, isFractionalCountable, needsProductLink } from "../utils";
import IngredientLinkButton from "./IngredientLinkButton";
import { formatDate } from "@/utils/helpers";
import { unitLabel } from "@/lib/i18nHelpers";

const itemStatusVariant: Record<
  string,
  "success" | "warning" | "secondary" | "danger"
> = {
  picked: "success",
  pending: "secondary",
  skipped: "warning",
  missing: "danger",
  unknown: "secondary",
};

interface Props {
  item: PickingItem;
  /** The last scan of this ingredient the server refused to act on, if any. */
  refusal?: PickingRefusal;
  onTap: (item: PickingItem) => void;
  onUndo: (item: PickingItem) => void;
  /** Set to offer linking in place on rows nothing could match. */
  recipeId?: string;
  onLinked?: () => void;
}

const PickingItemRow = memo(function PickingItemRow({
  item,
  refusal,
  onTap,
  onUndo,
  recipeId,
  onLinked,
}: Props) {
  const { t } = useTranslation("recipes");
  // A decision, not a sentence: an amount that cannot be halved is flagged
  // in amber. Read once, above the markup, so the unit reaches the screen
  // only through the resolver two lines below.
  const fractionalCountable = isFractionalCountable(
    item.quantity_to_pick,
    item.uom_symbol,
  );
  const variant = itemStatusVariant[item.status] ?? "secondary";
  // An ingredient with nothing to pick is not tappable — the row must not
  // pretend otherwise. That is a stock fact, so it reads the recommendation.
  const hasStock = item.recommended_item_id != null;
  const isDisabled =
    item.status === "skipped" || item.status === "missing" || !hasStock;
  const needsLink = needsProductLink(item);

  const activate = () => {
    if (item.status === "pending" && item.recommended_item_id) onTap(item);
    else if (item.status === "picked") onUndo(item);
  };

  return (
    <div
      onClick={isDisabled ? undefined : activate}
      onKeyDown={
        isDisabled
          ? undefined
          : (e) => {
              if (e.key === "Enter" || e.key === " ") {
                e.preventDefault();
                activate();
              }
            }
      }
      className={`flex items-center justify-between gap-3 px-5 py-3.5 transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-inset ${
        isDisabled
          ? "opacity-60 cursor-default"
          : "cursor-pointer hover:bg-surface active:bg-surface"
      }`}
      /* A row that cannot be tapped is not a button. Claiming the role
         anyway buried the link control this row now carries: a control
         nested inside role="button" is not reachable as its own thing. */
      role={isDisabled ? undefined : "button"}
      tabIndex={isDisabled ? undefined : 0}
    >
      <div className="flex items-center gap-3 min-w-0 flex-1">
        <span className="shrink-0 mt-0.5">
          {item.status === "picked" ? (
            <CheckCircle2 size={18} className="text-success-500" />
          ) : item.status === "missing" ? (
            <Package size={18} className="text-red-400" />
          ) : item.status === "unknown" ? (
            <Clock size={18} className="text-on-muted/60" />
          ) : (
            <Clock size={18} className="text-on-muted" />
          )}
        </span>
        <div className="min-w-0 flex-1">
          <p className="text-sm font-medium text-on line-clamp-2">
            {item.name}
          </p>
          {item.location && (
            <p className="text-xs text-on-secondary truncate mt-0.5">
              {item.location}
            </p>
          )}
          {needsLink && (
            <p className="text-xs text-on-muted mt-0.5">
              {t("picking.unlinked_badge")}
            </p>
          )}
          {refusal && (
            // The scan that was refused took nothing off the shelf, and the
            // toast saying so is gone in seconds. The row keeps the fact for
            // as long as the checklist is open.
            <p className="text-xs text-on-warning flex items-center gap-1 mt-0.5">
              <AlertTriangle
                size={11}
                aria-hidden="true"
                className="shrink-0"
              />
              {t(`picking.not_taken.${refusal}`)}
            </p>
          )}
          {item.fefo_expiry_date != null && (
            <p className="text-xs text-amber-600 flex items-center gap-0.5 mt-0.5">
              <AlertTriangle size={10} />
              {t("availability.fefo_expiry", {
                date: formatDate(item.fefo_expiry_date),
              })}
            </p>
          )}
        </div>
      </div>
      <div className="flex items-center gap-2 shrink-0">
        <span
          className={`text-xs whitespace-nowrap ${
            fractionalCountable
              ? "text-amber-600 font-medium"
              : "text-on-secondary"
          }`}
        >
          {fmtQty(item.quantity_to_pick)} {unitLabel(t, item.uom_symbol)}
        </span>
        <Badge variant={variant} className="text-xs">
          {t(`picking.status.${item.status}`)}
        </Badge>
        {needsLink && recipeId && (
          // Icon-only on a phone; the popover it opens does the naming.
          <span onClick={(e) => e.stopPropagation()}>
            <IngredientLinkButton
              ingredientId={item.ingredient_id}
              recipeId={recipeId}
              ingredientName={item.name}
              uomSymbol={item.uom_symbol}
              onLinked={onLinked}
              primary
            />
          </span>
        )}
        {item.status === "pending" && hasStock && (
          <ChevronRight size={14} className="text-on-muted" />
        )}
        {item.status === "picked" && (
          <span className="text-xs text-on-muted">
            {t("picking.undo_hint")}
          </span>
        )}
      </div>
    </div>
  );
});

export default PickingItemRow;
