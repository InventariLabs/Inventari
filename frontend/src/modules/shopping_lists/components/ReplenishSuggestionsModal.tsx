import { useState, useEffect, useMemo } from "react";
import { X, Sparkles, Package, Loader2, Minus, Plus, Zap } from "lucide-react";
import { useTranslation } from "react-i18next";
import Button from "@/components/ui/Button";
import { Sheet, SheetActions, SheetFooter } from "@/components/ui/Sheet";
import { toast } from "sonner";
import type {
  ShoppingListItemInput,
  SuggestedItem,
} from "@/modules/shopping_lists/types/shopping";
import { toAmount } from "@/utils/formatters";
import {
  useAddShoppingItemsToAList,
  useShoppingSuggestionsPreview,
} from "@/modules/shopping_lists/hooks/useShoppingLists";
import { shoppingListsApi } from "@/modules/shopping_lists/api/shopping-lists";
import { REPLENISH_SUGGESTION_SOURCES } from "../constants/replenishSources";
import { extractApiError } from "@/lib/errors";
import { unitLabel } from "@/lib/i18nHelpers";
import { Checkbox } from "@/module-sdk";

interface ReplenishSuggestionsModalProps {
  isOpen: boolean;
  onClose: () => void;
}

/** One row's identity, held across a refetch. The position in the list can
 *  shift when the engine answers again; the product cannot.
 *
 *  The engine's low-stock and consumption sources name a *template*, not an
 *  item, and one organization may hold two templates with the same name —
 *  so the template id is the identity where there is one. A proposal with
 *  neither id (no current source produces one — the expiring sources carry
 *  the item) falls back to source, name and position, which is a tie-break
 *  of last resort, not an identity. */
function suggestionKey(s: SuggestedItem, index: number): string {
  return s.item_id ?? s.template_id ?? `${s.source}:${s.name}:${index}`;
}

/** Whether two keyed number maps say the same thing.
 *
 *  The defaults effect runs whenever the query hands it a new array — and a
 *  refetch that answers with equal rows still hands over a new object. The
 *  write is skipped when the values match, so the screen does not re-render
 *  on every pass; a state write per pass is a render loop. */
function sameDefaults(
  prev: Record<string, number>,
  next: Record<string, number>,
): boolean {
  const keys = Object.keys(prev);
  return (
    keys.length === Object.keys(next).length &&
    keys.every((key) => prev[key] === next[key])
  );
}

/** The chosen suggestions as shopping-list rows, with whatever the reader
 *  changed about them on this screen. */
function rowsToAdd(
  selectedKeys: string[],
  suggestions: SuggestedItem[],
  quantities: Record<string, number>,
  priorities: Record<string, number>,
): ShoppingListItemInput[] {
  return suggestions
    .map((s, i) => ({ s, key: suggestionKey(s, i) }))
    .filter(({ key }) => selectedKeys.includes(key))
    .map(({ s, key }) => {
      return {
        item_id: s.item_id ?? undefined,
        template_id: s.template_id ?? undefined,
        category_id: s.category_id ?? undefined,
        name: s.name,
        quantity: quantities[key] || toAmount(s.quantity) || 1,
        uom_id: s.uom_id ?? undefined,
        priority: priorities[key] ?? s.priority ?? 0,
        estimated_price: s.estimated_price ?? undefined,
        notes: s.notes ?? undefined,
      };
    });
}

export default function ReplenishSuggestionsModal({
  isOpen,
  onClose,
}: ReplenishSuggestionsModalProps) {
  const { t } = useTranslation(["common", "shopping_lists"]);
  const [selectedKeys, setSelectedKeys] = useState<string[]>([]);
  const [quantities, setQuantities] = useState<Record<string, number>>({});
  const [priorities, setPriorities] = useState<Record<string, number>>({});

  // This hangs on the tile counting shortages, so it asks for shortages —
  // the same sources the dashboard's door asks with. The engine returns
  // every source it knows unless it is asked otherwise, and that is how a
  // button promising to replenish shortages opened a screenful of
  // products that had *expired*.
  const { data: suggestionsData, isLoading } = useShoppingSuggestionsPreview(
    isOpen,
    REPLENISH_SUGGESTION_SOURCES,
  );

  const suggestions = useMemo(
    () => suggestionsData?.suggestions || [],
    [suggestionsData?.suggestions],
  );

  // The sheet stays mounted while closed, so a tick made in one visit
  // outlived Cancel and came back at the next opening — and the row keys
  // are the products now, so it could also land on a different proposal
  // once the engine answered again. Every opening starts from nothing:
  // the ticks, the quantities and the priorities, all three keyed by the
  // row's identity rather than by its position.
  useEffect(() => {
    if (!isOpen) return;
    // Same content, same state: an engine answer that arrives as a new array
    // with equal rows must not re-render the screen, and an empty tick list
    // must not become a new empty array on every pass — the effect below
    // runs after each render the query gives a new array to, and a
    // state-write per pass is a render loop.
    setSelectedKeys((prev) => (prev.length === 0 ? prev : []));
    if (suggestions.length === 0) return;
    // The subtitle asks the reader to choose, so the screen starts with
    // nothing chosen — the confirm disables itself at zero, which is what
    // keeps a hasty click from adding the whole list. Quantities and
    // priorities are not a choice, only defaults the steppers can move;
    // they may start filled, and they follow the row's identity, not its
    // position in the engine's answer.
    const initialQuantities: Record<string, number> = {};
    const initialPriorities: Record<string, number> = {};
    suggestions.forEach((s, i) => {
      const key = suggestionKey(s, i);
      initialQuantities[key] = toAmount(s.quantity) ?? 1;
      initialPriorities[key] = s.priority || 0;
    });
    setQuantities((prev) =>
      sameDefaults(prev, initialQuantities) ? prev : initialQuantities,
    );
    setPriorities((prev) =>
      sameDefaults(prev, initialPriorities) ? prev : initialPriorities,
    );
  }, [suggestions, isOpen]);

  // The list is made here, at the moment somebody decides to buy
  // something — not when they open the preview.
  const addItemsMutation = useAddShoppingItemsToAList();

  const handleToggleItem = (key: string) => {
    setSelectedKeys((prev) =>
      prev.includes(key) ? prev.filter((k) => k !== key) : [...prev, key],
    );
  };

  const handleUpdateQuantity = (key: string, delta: number) => {
    setQuantities((prev) => ({
      ...prev,
      [key]: Math.max(1, (prev[key] || 1) + delta),
    }));
  };

  const handleTogglePriority = (key: string) => {
    setPriorities((prev) => ({
      ...prev,
      [key]: prev[key] === 2 ? 0 : 2,
    }));
  };

  const handleConfirm = () => {
    const itemsToAdd = rowsToAdd(
      selectedKeys,
      suggestions,
      quantities,
      priorities,
    );

    if (itemsToAdd.length === 0) {
      onClose();
      return;
    }

    void (async () => {
      let listId: string;
      try {
        listId = await shoppingListsApi.ensureActiveList();
      } catch (error) {
        toast.error(
          extractApiError(error, t("shopping_lists:toasts.addItemsFailed")),
        );
        return;
      }
      addItemsMutation.mutate(
        { listId, items: itemsToAdd },
        {
          onSuccess: (data) => {
            toast.success(
              t("dashboard.replenishSuccess") ||
                `Added ${(data as unknown[]).length} items`,
            );
            onClose();
          },
          onError: (error: unknown) => {
            const err = error as { response?: { status?: number } };
            if (err?.response?.status === 404) {
              toast.error(t("shopping_lists:toasts.shoppingListGone"));
            } else {
              toast.error(
                extractApiError(
                  error,
                  t("shopping_lists:toasts.addItemsFailed"),
                ),
              );
            }
          },
        },
      );
    })();
  };

  return (
    <Sheet
      open={isOpen}
      onClose={onClose}
      maxWidth="md"
      zIndex="confirm"
      aria-label={t("dashboard.replenishModalTitle")}
      className="overflow-hidden"
    >
      {/* Handle for mobile */}
      <div className="w-12 h-1.5 bg-surface-inset rounded-full mx-auto my-3 sm:hidden shrink-0" />

      {/* Header */}
      <div className="px-6 py-5 border-b flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 bg-indigo-50 text-indigo-600 rounded-xl flex items-center justify-center shrink-0">
            <Sparkles size={20} />
          </div>
          <div>
            <h3 className="text-lg font-semibold text-on leading-none">
              {t("dashboard.replenishModalTitle")}
            </h3>
            <p className="text-xs text-on-secondary mt-1">
              {t("dashboard.replenishModalDesc")}
            </p>
          </div>
        </div>
        <Button
          variant="ghost"
          size="icon"
          onClick={onClose}
          aria-label={t("common:a11y.close")}
          className="text-on-muted"
        >
          <X size={18} />
        </Button>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto p-4 space-y-2">
        {isLoading ? (
          <div className="py-12 flex flex-col items-center justify-center gap-3">
            <Loader2 className="animate-spin text-indigo-600" size={32} />
            <p className="text-sm font-medium text-on-muted">
              {t("messages.loading")}
            </p>
          </div>
        ) : suggestions.length === 0 ? (
          <div className="py-24 text-center">
            <div className="w-16 h-16 bg-surface text-on-muted rounded-full flex items-center justify-center mx-auto mb-4">
              <Package size={32} />
            </div>
            <p className="text-on-muted font-medium">
              {t("dashboard.noSuggestions")}
            </p>
          </div>
        ) : (
          suggestions.map((item, index) => {
            const key = suggestionKey(item, index);
            const isSelected = selectedKeys.includes(key);
            const currentQty = quantities[key] || item.quantity || 1;
            const isUrgent = priorities[key] === 2;
            return (
              <div
                key={key}
                className={`flex flex-col p-3 rounded-xl transition-all border ${
                  isSelected
                    ? isUrgent
                      ? "bg-red-50 border-red-100"
                      : "bg-indigo-50 border-indigo-50"
                    : "bg-transparent border-transparent hover:bg-surface"
                }`}
              >
                <div className="flex items-center justify-between">
                  {/* The row's tick is a real checkbox inside a label: the
                      whole area stays one target, and Tab reaches it — a
                      div with onClick left the row unreachable from the
                      keyboard the moment nothing was ticked upfront. */}
                  <label className="flex items-center gap-3 min-w-0 flex-1 cursor-pointer">
                    <Checkbox
                      checked={isSelected}
                      onChange={() => handleToggleItem(key)}
                      className={`h-5 w-5 shrink-0 rounded-md ${
                        isUrgent ? "accent-red-600" : "accent-indigo-600"
                      }`}
                    />
                    <div className="min-w-0">
                      <p
                        className={`font-semibold truncate text-sm ${
                          isSelected
                            ? isUrgent
                              ? "text-red-900"
                              : "text-indigo-900"
                            : "text-on"
                        }`}
                      >
                        {item.name}
                      </p>
                      {item.notes && (
                        <p className="text-[10px] text-on-secondary truncate italic">
                          {item.notes}
                        </p>
                      )}
                    </div>
                  </label>

                  <div className="flex items-center gap-2">
                    {/* Priority toggle */}
                    <Button
                      variant="ghost"
                      size="iconSm"
                      onClick={(e) => {
                        e.stopPropagation();
                        handleTogglePriority(key);
                      }}
                      className={`${
                        isUrgent
                          ? "bg-red-600 text-white shadow-sm ring-2 ring-red-100 hover:bg-red-600 active:bg-red-600"
                          : "bg-surface-raised text-on-muted hover:text-on-secondary"
                      }`}
                      title={t("a11y.urgent")}
                      aria-label={t("a11y.urgent")}
                    >
                      <Zap
                        size={14}
                        fill={isUrgent ? "currentColor" : "none"}
                      />
                    </Button>

                    {/* Quantity controls */}
                    <div className="flex items-center gap-1 bg-surface-card p-0.5 rounded-lg border border-border shadow-sm">
                      <Button
                        variant="ghost"
                        size="iconSm"
                        onClick={(e) => {
                          e.stopPropagation();
                          handleUpdateQuantity(key, -1);
                        }}
                        aria-label={t("actions.decrease")}
                        className="rounded-md text-on-muted"
                      >
                        <Minus size={14} />
                      </Button>
                      <div className="min-w-[36px] text-center flex flex-col items-center">
                        <span className="text-xs font-medium text-on leading-none">
                          {currentQty}
                        </span>
                        {/* "—" rather than "pcs" for a product with no unit:
                            the suggestion would otherwise order pieces of
                            something measured in grams. */}
                        <span className="text-[10px] font-medium text-on-muted">
                          {unitLabel(t, item.uom_symbol) || "—"}
                        </span>
                      </div>
                      <Button
                        variant="ghost"
                        size="iconSm"
                        onClick={(e) => {
                          e.stopPropagation();
                          handleUpdateQuantity(key, 1);
                        }}
                        aria-label={t("actions.increase")}
                        className="rounded-md text-on-muted"
                      >
                        <Plus size={14} />
                      </Button>
                    </div>
                  </div>
                </div>
              </div>
            );
          })
        )}
      </div>

      {/* Footer */}
      <SheetFooter>
        <SheetActions className="gap-3">
          <Button
            size="content"
            onClick={onClose}
            variant="ghost"
            className="h-12 rounded-xl text-on-secondary font-medium"
          >
            {t("actions.cancel")}
          </Button>
          <Button
            size="content"
            onClick={handleConfirm}
            disabled={
              addItemsMutation.isPending ||
              (suggestions.length > 0 && selectedKeys.length === 0)
            }
            className="h-12 bg-indigo-600 hover:bg-indigo-700 text-white rounded-xl font-semibold shadow-md shadow-indigo-100 transition-all active:scale-95 disabled:opacity-50"
          >
            {addItemsMutation.isPending ? (
              <Loader2 className="animate-spin" size={20} />
            ) : (
              t("dashboard.addSelected", { count: selectedKeys.length })
            )}
          </Button>
        </SheetActions>
      </SheetFooter>
    </Sheet>
  );
}
