import { useTranslation } from "react-i18next";
import { Sparkles } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { InlineQueryError } from "@/components/ui/QueryResult";
import { useCanWrite } from "@/hooks/useCanWrite";
import type { SlotDataMap } from "@/lib/moduleRegistry";
import { useShoppingSuggestionsPreview } from "../../hooks/useShoppingLists";
import { REPLENISH_SUGGESTION_SOURCES } from "../../constants/replenishSources";

type Props = { data: SlotDataMap["dashboard_replenish_action"] };

/**
 * The dashboard's "replenish" door.
 *
 * The door and the modal behind it ask the engine the same question, so
 * they cannot disagree: the button used to hang on the tile counting
 * shortages — a different query with different filters — and stayed open
 * over an empty modal after the run's proposals were already on a list.
 * Same hook, same sources, same cache entry as the modal's.
 *
 * The suggestions become a shopping list; for an account that may not write
 * one the door would open a modal whose every answer is refused. The
 * engine's own answer decides the rest — not a condition on its way in.
 *
 * With the door shut the card says why a product with stock in use outside
 * the shelves is neither flagged nor proposed, so a missing button is a
 * stated rule and not a silence.
 */
export default function ReplenishActionSlot({ data }: Props) {
  const { t } = useTranslation("common");
  const canWrite = useCanWrite("shopping_lists");
  const {
    data: preview,
    error,
    refetch,
  } = useShoppingSuggestionsPreview(true, REPLENISH_SUGGESTION_SOURCES);

  // A preview that failed is not "nothing to replenish": the door would
  // vanish and the card read as if stock needed no ordering.
  if (error) {
    return <InlineQueryError error={error} onRetry={() => void refetch()} />;
  }
  if (!preview) return null;
  if (!canWrite || preview.suggestions.length === 0) {
    return (
      <p className="text-xs text-on-secondary">
        {t("common:dashboard.replenishPolicy")}
      </p>
    );
  }
  return (
    <Button
      variant="outline"
      size="sm"
      leftIcon={<Sparkles size={16} />}
      onClick={data.onOpen}
    >
      {t("common:dashboard.replenishAll")}
    </Button>
  );
}
