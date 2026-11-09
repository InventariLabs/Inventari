import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import { Share2 } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { InlineQueryError } from "@/components/ui/QueryResult";
import type { WhereUsedItem } from "@/modules/maker/api/bom";
import { useWhereUsed } from "@/modules/maker/hooks/useBom";
import { formatQuantityLocalized } from "@/lib/i18nHelpers";
import type { Item } from "@/types";

interface WhereUsedSlotProps {
  data?: {
    item?: Item;
    requestLeave?: (go: () => void) => void;
  };
}

/**
 * where-used view on the product (ingredient) card.
 *
 * Rendered via the `item_edit_extra` slot next to `BoMEntrySlot` — shows
 * which production BOMs consume this template as an ingredient, with a link
 * to each of them.
 *
 * Nothing to show means nothing rendered, which is what the neighbouring slot
 * does in the same situation. "Not used in any BOM" is true of most products
 * in most organizations, carries no action, and cost a heading and a line in
 * every product form to say.
 */
export function WhereUsedSlot({ data }: WhereUsedSlotProps) {
  const { t } = useTranslation("maker");
  const navigate = useNavigate();
  const templateId = data?.item?.template_id;
  const {
    data: whereUsed,
    isLoading,
    isError,
    error,
    refetch,
  } = useWhereUsed(templateId ?? undefined);
  if (!templateId) return null;

  // "Not used in any BOM" renders as nothing, so a failed read would pass for
  // it; say that the answer is missing instead.
  if (isError) {
    return (
      <div className="mt-3" data-testid="maker-where-used">
        <h4 className="flex items-center gap-1.5 text-xs uppercase tracking-widest text-on-muted font-medium mb-1.5">
          <Share2 size={13} />
          {t("whereUsed.title")}
        </h4>
        <InlineQueryError error={error} onRetry={() => void refetch()} />
      </div>
    );
  }

  const items: WhereUsedItem[] = whereUsed?.items ?? [];
  if (isLoading || items.length === 0) return null;

  const open = (recipeId: string) => {
    const go = () => navigate(`/maker/recipes/${recipeId}`);
    return data?.requestLeave ? data.requestLeave(go) : go();
  };

  return (
    <div className="mt-3" data-testid="maker-where-used">
      <h4 className="flex items-center gap-1.5 text-xs uppercase tracking-widest text-on-muted font-medium mb-1.5">
        <Share2 size={13} />
        {t("whereUsed.title")}
      </h4>
      <ul className="space-y-1">
        {items.map((item) => (
          <li key={item.recipe_id} className="flex items-baseline gap-2">
            <Button
              variant="link"
              size="inline"
              type="button"
              className="text-sm text-on-primary truncate"
              data-testid="maker-where-used-link"
              onClick={() => open(item.recipe_id)}
            >
              {item.recipe_name}
            </Button>
            <span className="text-xs text-on-muted whitespace-nowrap">
              {t("whereUsed.perBatch", {
                qty: formatQuantityLocalized(t, item.qty_per_batch, item.unit),
              })}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

export default WhereUsedSlot;
