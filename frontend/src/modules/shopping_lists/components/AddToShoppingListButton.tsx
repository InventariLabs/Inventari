import { useTranslation } from "react-i18next";
import { extractApiError } from "@/lib/errors";
import { ShoppingCart, Loader2 } from "lucide-react";
import { useQuickAddToShoppingList } from "@/modules/shopping_lists/hooks/useShoppingLists";
import { useCanWrite } from "@/hooks/useCanWrite";
import { toast } from "sonner";
import type { SlotDataMap } from "@/lib/moduleRegistry";
import { Button } from "@/components/ui/Button";

interface AddToShoppingListButtonProps {
  data: SlotDataMap["quick_action_extra"];
}

/**
 * The product sheet's "Add to shopping list", contributed to the quick-action
 * slot. Its only act is adding a row to a list, which the shopping-lists
 * router guards with `shopping_lists:write` — the module's key, not the one
 * the page around it asks about. The caller cannot ask it: the slot hands the
 * component the item and nothing else, and a read-only account used to be
 * offered the button and refused on click.
 */
export default function AddToShoppingListButton({
  data,
}: AddToShoppingListButtonProps) {
  const { item } = data;
  const { t } = useTranslation(["items", "shopping_lists"]);
  const canWrite = useCanWrite("shopping_lists");

  const mutation = useQuickAddToShoppingList();

  if (!canWrite) {
    return null;
  }

  return (
    <Button
      variant="ghost"
      size="sm"
      onClick={() =>
        mutation.mutate(
          {
            name: item.name,
            quantity: 1,
            unit: item.uom?.symbol || undefined,
            item_id: item.id,
          },
          {
            onSuccess: () =>
              toast.success(
                t("messages.addedToShoppingList", {
                  defaultValue: "Added to shopping list!",
                }),
              ),
            onError: (error: unknown) =>
              toast.error(
                extractApiError(error, t("messages.addToShoppingListFailed")),
              ),
          },
        )
      }
      disabled={mutation.isPending}
      className="text-violet-500 hover:text-violet-700 hover:bg-violet-50"
    >
      {mutation.isPending ? (
        <Loader2 size={15} className="animate-spin" />
      ) : (
        <ShoppingCart size={15} />
      )}
      <span>{t("addToShoppingList")}</span>
    </Button>
  );
}
