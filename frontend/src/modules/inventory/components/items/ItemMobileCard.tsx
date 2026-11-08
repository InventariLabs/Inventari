import { isVirtualUsage } from "@/modules/shared/lib/storageUsage";
import { memo, useEffect, useState, useRef } from "react";
import { categoryLabel } from "@/lib/i18nHelpers";
import { useTranslation } from "react-i18next";
import {
  CheckCircle,
  MapPin,
  Trash2,
  Undo2,
  Barcode,
  Hash,
  MoreVertical,
  TrendingDown,
  Tag,
} from "lucide-react";
import { Card } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { Checkbox } from "@/components/ui/Checkbox";
import Button from "@/components/ui/Button";
import { Tooltip } from "@/components/ui/Tooltip";
import type { Item, CategoryDTO, StorageLocationSummary } from "@/types";
import { itemSku, productCode } from "@/types";
import { toast } from "sonner";

import ExpiryChip from "./ExpiryChip";
import { toAmount } from "@/utils/formatters";
import {
  badgeQuantity,
  usePartialPackage,
} from "@/modules/shared/hooks/usePartialPackage";
import { partialPackageSentence } from "@/utils/partialPackage";

/** Once per app session the first card peeks sideways — see the effect below. */
let swipeHintShown = false;

interface ItemMobileCardProps {
  item: Item;
  storages?: StorageLocationSummary[];
  categories?: CategoryDTO[];
  onItemClick: (item: Item) => void;
  onConsume: (itemId: string) => void;
  /** Whether to offer consuming and the swipe-to-delete affordance. */
  canWrite?: boolean;
  onSetThreshold: (item: Item) => void;
  /** Opens the per-item actions sheet (owned by the list, like every modal). */
  onOpenActions: (item: Item) => void;
  consumingId: string | null;
  isSelected: boolean;
  onToggleSelect: (id: string) => void;
  /** List-driven selection mode: checkbox replaces the quantity badge, the
      row tap toggles selection, swipe and quick actions stand down. */
  selectionMode?: boolean;
  /** Deletes for real once the Undo window closes — that window is the
 confirmation, so this path asks nothing further. */
  onSwipeDelete?: (itemId: string) => void;
  /** First row of the list: play the one-time swipe affordance. */
  swipeHint?: boolean;
}

/**
 * Promise a deletion, then keep the promise unless it is taken back.
 *
 * The undo window stands in for a confirmation dialog: the toast says the
 * deletion is pending and the deletion then happens. It used to announce a
 * removal that had not happened and ask for permission five seconds later,
 * when the reader was already looking elsewhere.
 *
 * Outside the component because the card sits at the complexity ceiling and
 * this is a self-contained promise about a name and a callback.
 */
function scheduleUndoableDelete(
  name: string,
  onConfirmed: () => void,
  t: (key: string, opts?: Record<string, unknown>) => string,
): () => void {
  let undone = false;
  let timerId: number | null = null;
  const toastId = toast.success(
    () => (
      <div className="flex items-center justify-between gap-4 w-full">
        <span className="font-medium text-sm">
          {t("items:messages.deletePending", { name })}
        </span>
        <Button
          onClick={() => {
            undone = true;
            toast.dismiss(toastId);
          }}
          variant="ghost"
          size="sm"
          className="font-semibold text-sm text-white bg-surface-card/10 hover:bg-surface-card/20"
        >
          <Undo2 size={14} />
          {t("common:actions.undo")}
        </Button>
      </div>
    ),
    {
      duration: 5000,
      style: {
        background: "#1F2937",
        color: "#fff",
        padding: "12px 16px",
        borderRadius: "12px",
        minWidth: "320px",
      },
    },
  );

  timerId = window.setTimeout(() => {
    timerId = null;
    if (!undone) onConfirmed();
  }, 5000);

  // The card owns this promise: the id travels back to whoever scheduled it,
  // so an unmount inside the window takes the timer (and the toast that
  // promises a deletion) back instead of firing the delete for an audience
  // that has already left.
  return () => {
    if (timerId !== null) {
      clearTimeout(timerId);
      timerId = null;
    }
    toast.dismiss(toastId);
  };
}

/**
 * The codes a product is found by: barcode, SKU, serial number.
 *
 * Each is optional and most rows carry none, so they are three conditions
 * that say nothing about the rest of the card — which is exactly what a
 * separate component is for. The card is at the complexity ceiling and these
 * were three of its branches.
 */
function ItemIdentifiers({
  item,
  t,
}: {
  item: Item;
  t: (key: string, opts?: Record<string, unknown>) => string;
}) {
  const row =
    "flex items-center gap-1 font-mono text-[10px] text-on-muted mb-1";
  return (
    <>
      {productCode(item) && (
        <div className={row}>
          <Barcode size={10} />
          <span>{productCode(item)}</span>
        </div>
      )}
      {itemSku(item) && (
        <div className={row}>
          <Tag size={10} />
          <span>{itemSku(item)}</span>
        </div>
      )}
      {item.serial_number && (
        <div className={row} title={t("items:fields.serial_number")}>
          <Hash size={10} />
          <span>{item.serial_number}</span>
        </div>
      )}
    </>
  );
}

/**
 * The quantity on the card's left: the product photo with the badge over it,
 * or the badge alone. It opens the threshold sheet for an account that may
 * save one; for any other it is only the quantity, because the sheet's save
 * would answer 403.
 */
function QuantityBadge({
  item,
  badge,
  canWrite,
  onSetThreshold,
}: {
  item: Item;
  badge: { number: string; unit: string };
  canWrite: boolean;
  onSetThreshold: (item: Item) => void;
}) {
  const { t } = useTranslation(["items"]);
  // The quantity badge opens the threshold dialog, but announced itself as
  // "3" or "3 PCS." — a `title` creates no accessible name once the element
  // has content of its own. An `aria-label` then spelled the shown parts
  // "3 kg" mid-sentence, which is not the run of text a voice user sees
  // (WCAG 2.5.3): what the badge shows leads its name now, and this purpose
  // follows, read but not shown.
  const alertFor = t("items:setStockAlertForItem", { name: item.name });
  const badgeNumber = badge.number;
  const badgeClass = "bg-surface-raised text-on";
  const badgeFace = (
    <>
      <span
        // Measured on what the badge shows, not on what the
        // column stores: "1.000" is five characters and "1"
        // is one, and the size was chosen off the padding.
        className={`font-medium leading-none mb-0.5 tabular-nums ${
          badgeNumber.length > 3 ? "text-[10px]" : "text-sm"
        }`}
      >
        {badgeNumber}
      </span>
      <span className="text-[10px] font-medium tracking-tight leading-none max-w-full px-0.5">
        {/* Same rule as the desktop row: the slot always says something.
            A bare number reads as complete and lets the reader supply
            "pcs" themselves. */}
        {badge.unit || "—"}
      </span>
    </>
  );
  return (
    <div className="shrink-0 relative">
      {item.image_url ? (
        <>
          <img
            src={item.image_url}
            alt={item.name}
            loading="lazy"
            className="w-12 h-12 rounded-xl object-cover border border-border"
          />
          {canWrite ? (
            <Button
              onClick={(e) => {
                e.stopPropagation();
                onSetThreshold(item);
              }}
              variant="ghost"
              size="contentSm"
              // The badge sits on a 48px thumbnail, so it cannot grow to
              // 44px without covering the photo. The plan allows exactly
              // this: the visual size stays, the hit area is extended to
              // 44px with a transparent pseudo-element.
              className="absolute -top-1.5 -right-1.5 px-1.5 py-0.5 bg-gray-900 text-white text-[10px] font-medium rounded-md shadow-sm ring-1 ring-white hover:bg-amber-600 after:absolute after:-inset-[13px] after:content-[''] md:after:hidden"
              title={t("setStockAlert")}
            >
              {badgeNumber}
              {/* The unit has no room on the photo; the name keeps it. */}{" "}
              <span className="sr-only">
                {badge.unit} {alertFor}
              </span>
            </Button>
          ) : (
            <span className="absolute -top-1.5 -right-1.5 px-1.5 py-0.5 bg-gray-900 text-white text-[10px] font-medium rounded-md shadow-sm ring-1 ring-white">
              {badgeNumber}
              <span className="sr-only"> {badge.unit}</span>
            </span>
          )}
        </>
      ) : (
        <>
          {" "}
          {canWrite ? (
            <Button
              onClick={(e) => {
                e.stopPropagation();
                onSetThreshold(item);
              }}
              variant="ghost"
              size="contentSm"
              className={`min-h-11 md:min-h-0 w-11 flex-shrink-0 flex-col rounded-xl shadow-inner overflow-hidden aspect-square ${badgeClass}`}
              title={t("setStockAlert")}
            >
              {badgeFace} <span className="sr-only">{alertFor}</span>
            </Button>
          ) : (
            <div
              className={`min-h-11 md:min-h-0 w-11 flex-shrink-0 flex flex-col items-center justify-center rounded-xl shadow-inner overflow-hidden aspect-square ${badgeClass}`}
            >
              {badgeFace}
            </div>
          )}
        </>
      )}
    </div>
  );
}

export default memo(function ItemMobileCard({
  item,
  storages,
  categories,
  onItemClick,
  onConsume,
  onSetThreshold,
  onOpenActions,
  consumingId,
  isSelected,
  onToggleSelect,
  selectionMode = false,
  onSwipeDelete,
  swipeHint = false,
  canWrite = true,
}: ItemMobileCardProps) {
  const { t } = useTranslation(["items", "categories", "common"]);
  // The card's swipe gestures write, and two different things stand them
  // down: selection mode, where a drag must scroll, and an account that may
  // not write at all. One name for both, because the swipes behave
  // identically either way.
  const locked = selectionMode || !canWrite;
  const [swipeX, setSwipeX] = useState(0);
  const [isSwiping, setIsSwiping] = useState(false);
  const [hinting, setHinting] = useState(false);
  const touchStartX = useRef(0);
  const touchStartY = useRef(0);
  const cardRef = useRef<HTMLDivElement>(null);
  // The undoable delete this card scheduled: unmount takes it back, because
  // a deletion nobody can undo anymore must not fire for an audience that
  // has already left.
  const pendingDeleteCancelRef = useRef<(() => void) | null>(null);

  useEffect(() => {
    return () => {
      pendingDeleteCancelRef.current?.();
      pendingDeleteCancelRef.current = null;
    };
  }, []);

  // Swipe affordance: gestures are shortcuts for the experienced,
  // never the only path — but a gesture nobody discovers is as good as none.
  // The first card of the list peeks 12px right and slides back, exactly once
  // per app session; users asking for reduced motion get no theatrics.
  useEffect(() => {
    if (!swipeHint || swipeHintShown || locked) return;
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    swipeHintShown = true;
    setHinting(true);
    const out = setTimeout(() => setSwipeX(12), 250);
    const back = setTimeout(() => {
      setSwipeX(0);
      setHinting(false);
    }, 450);
    return () => {
      clearTimeout(out);
      clearTimeout(back);
    };
  }, [swipeHint, locked]);

  const handleTouchStart = (e: React.TouchEvent) => {
    touchStartX.current = e.touches[0].clientX;
    touchStartY.current = e.touches[0].clientY;
  };

  const handleTouchMove = (e: React.TouchEvent) => {
    // Swipe is the selection mode's enemy: while checkboxes are up, a drag
    // must scroll, never consume or delete. Nor does a reader's drag do
    // either — both ends of the gesture are writes.
    if (locked) return;
    const deltaX = e.touches[0].clientX - touchStartX.current;
    const deltaY = Math.abs(e.touches[0].clientY - touchStartY.current);

    // Activate swipe only when horizontal movement is stronger than vertical.
    if (Math.abs(deltaX) > deltaY && Math.abs(deltaX) > 10) {
      setIsSwiping(true);
      setSwipeX(deltaX);
    }
  };

  const handleTouchEnd = () => {
    if (locked) return;
    if (!isSwiping) {
      setSwipeX(0);
      return;
    }

    const threshold = 100;

    if (swipeX > threshold) {
      // Swipe right -> consume
      setSwipeX(0);
      setIsSwiping(false);
      onConsume(item.id);
    } else if (swipeX < -threshold && onSwipeDelete) {
      // Swipe left -> delete, with the Undo window standing in for the
      // confirmation dialog. The toast promises a deletion that is
      // still pending, and the deletion then happens — it used to announce a
      // removal that had not happened and ask for permission five seconds
      // later, when the user was already looking elsewhere.
      setSwipeX(0);
      setIsSwiping(false);

      // A second swipe inside the window takes the first promise back before
      // it is overwritten — a cancel nobody holds is a timer nobody owns,
      // which is exactly the failure the gate on this file exists for.
      pendingDeleteCancelRef.current?.();
      pendingDeleteCancelRef.current = scheduleUndoableDelete(
        item.name,
        () => onSwipeDelete(item.id),
        t,
      );
    } else {
      // Threshold not reached, return to initial position.
      setSwipeX(0);
      setIsSwiping(false);
    }
  };

  const getStorageName = (
    storageId: string | null | undefined,
    shelfLocation?: string | null,
  ) => {
    if (!storageId)
      return String(t("unknown", { ns: "common", defaultValue: "Unknown" }));
    // The places have not arrived yet: a record is not "Unknown" for as long
    // as the list that names it is still on its way.
    if (!storages) return "";
    const storage = storages.find((s) => s.id === storageId);
    if (!storage)
      return String(t("unknown", { ns: "common", defaultValue: "Unknown" }));
    // A used-up record is filed under a system place: its name says nothing.
    if (isVirtualUsage(storage.usage)) return t("items:usedUpPlace");

    // Show leaf name only (+ shelf if present)
    return shelfLocation ? `${storage.name} · ${shelfLocation}` : storage.name;
  };

  const getCategoryName = (categoryId: string | null | undefined) => {
    if (!categoryId) return "";
    const category = categories?.find((c) => c.id === categoryId);
    if (!category) return "";
    return categoryLabel(t, category.code, category.name);
  };

  const swipeProgress = Math.min(Math.abs(swipeX) / 100, 1);
  const backgroundColor =
    swipeX > 0
      ? `rgba(16, 185, 129, ${swipeProgress * 0.2})` // green for consume
      : swipeX < 0
        ? `rgba(239, 68, 68, ${swipeProgress * 0.2})` // red for delete
        : "transparent";

  const hasThreshold = item.min_quantity != null;
  // The quantity crosses the wire as a Decimal string; the comparison runs
  // on the number it denotes (TECHNICAL_DECISIONS §18).
  const isLow =
    hasThreshold && (toAmount(item.quantity) ?? 0) <= (item.min_quantity ?? 0);

  // A partly used package says what is left in the product's own weight or
  // volume unit; the badge carries the remainder and the line below the
  // name carries the full sentence.
  const partial = usePartialPackage()(item);
  const badge = badgeQuantity(t, item, partial);

  return (
    <div
      ref={cardRef}
      data-testid="item-row"
      className="relative overflow-hidden rounded-xl"
      onTouchStart={handleTouchStart}
      onTouchMove={handleTouchMove}
      onTouchEnd={handleTouchEnd}
    >
      {/* Background actions */}
      <div className="absolute inset-0 flex items-center justify-between px-6">
        <div
          className={`flex items-center gap-2 transition-opacity ${swipeX > 50 ? "opacity-100" : "opacity-0"}`}
        >
          <CheckCircle size={24} className="text-accent-600" />
          <span className="font-semibold text-accent-600">
            {t("items:actions.consume")}
          </span>
        </div>
        <div
          className={`flex items-center gap-2 transition-opacity ${swipeX < -50 ? "opacity-100" : "opacity-0"}`}
        >
          <span className="font-semibold text-red-600">
            {t("common:actions.delete")}
          </span>
          <Trash2 size={24} className="text-red-600" />
        </div>
      </div>

      {/* Main card */}
      <Card
        hoverable
        className={`p-3 flex items-center gap-3 transition-all ${
          isSelected
            ? "bg-primary-50 border-primary-200"
            : "bg-surface-card border-border"
        }`}
        style={{
          transform: `translateX(${swipeX}px)`,
          transition: isSwiping
            ? "none"
            : `transform ${hinting ? "0.2s" : "0.3s"} ease-out`,
          backgroundColor: isSwiping ? backgroundColor : undefined,
        }}
      >
        {/* Left column: the selection checkbox in selection mode, the
            quantity badge otherwise — the control costs 0px at rest, which
            matters on a 390px card. */}
        {selectionMode ? (
          <div className="shrink-0 flex items-center justify-center w-11 aspect-square">
            <Checkbox
              touchTarget
              checked={isSelected}
              onChange={() => onToggleSelect(item.id)}
              aria-label={t("items:actions.select", {
                defaultValue: "Select {{name}}",
                name: item.name,
              })}
            />
          </div>
        ) : (
          /* Product Image or Quantity */
          <QuantityBadge
            item={item}
            badge={badge}
            canWrite={canWrite}
            onSetThreshold={onSetThreshold}
          />
        )}

        {/* Main Info — the row's primary target is a real button, so the
            product is reachable by keyboard. Its accessible name is computed
            from the content — name, location, expiry, "Low" — because a fixed
            aria-label would silence every metadata line the eye can see.
            Nothing interactive may nest inside: the quantity badge keeps its
            own column to the left.
            Left at 228x38 below `md` on purpose: a row is aimed at, a control
            is hit — see UI_GUIDELINES §14.1b before padding it to 44. */}
        {/* eslint-disable-next-line no-restricted-syntax -- full-width content target with the card's own layout, not a chrome button; Button variants would impose padding/height/rounding */}
        <button
          type="button"
          // The focus ring is the app's, not Chrome's default outline — the
          // same token set `<Button>` uses.
          className="flex-1 min-w-0 text-left rounded-lg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
          onClick={() =>
            // Two interaction models must never share one target: while the
            // list is in selection mode the row tap selects, it never opens.
            selectionMode ? onToggleSelect(item.id) : onItemClick(item)
          }
        >
          <h3 className="text-sm font-semibold text-on truncate leading-tight mb-1">
            {item.name}
          </h3>

          <ItemIdentifiers item={item} t={t} />

          <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
            <div className="flex items-center gap-1 text-[10px] font-medium text-on-muted uppercase tracking-tight">
              <MapPin size={10} className="text-on-muted" />
              <span
                className="truncate max-w-[140px]"
                title={getStorageName(item.location_id, item.shelf_location)}
              >
                {getStorageName(item.location_id, item.shelf_location)}
              </span>
            </div>

            {partial && (
              <span className="text-xs font-medium text-on-secondary">
                {partialPackageSentence(t, partial)}
              </span>
            )}

            {getCategoryName(item.category_id) && (
              <div className="flex items-center gap-1 text-[10px] font-medium text-on-secondary uppercase tracking-tight">
                <span className="w-2 h-2 rounded-full bg-current opacity-50 shrink-0" />
                <span>{getCategoryName(item.category_id)}</span>
              </div>
            )}

            <ExpiryChip item={item} compact />

            {/* Low stock speaks in a word, not in a 4px shade of amber
. "Has a threshold but is fine" carries no signal at
                all — that is a product setting, not list information. */}
            {isLow && (
              <Badge variant="warning" className="gap-1 px-1.5 py-0">
                <TrendingDown size={10} />
                <span>{t("items:stock.lowStock")}</span>
              </Badge>
            )}
          </div>
        </button>

        {/* Quick Action Buttons — stood down in selection mode, so the two
            interaction models never share the card. The "⋯" goes with them
            for a reader only as far as writing goes: its sheet still leads
            with "Product details", the one door from the list to the
            product page, so the "⋯" stays and the consume button goes. */}
        {!selectionMode && (
          <ItemCardQuickActions
            item={item}
            canWrite={canWrite}
            consumingId={consumingId}
            onConsume={onConsume}
            onOpenActions={onOpenActions}
          />
        )}
      </Card>
    </div>
  );
});

/**
 * The card's two quick actions, in their own component so the card stays
 * inside its frozen length — the same reason `scheduleUndoableDelete` lives
 * outside it. Each icon's words are one variable shared by its accessible
 * name and its tooltip, so the two cannot drift.
 */
function ItemCardQuickActions({
  item,
  canWrite,
  consumingId,
  onConsume,
  onOpenActions,
}: {
  item: Item;
  canWrite: boolean;
  consumingId: string | null;
  onConsume: (itemId: string) => void;
  onOpenActions: (item: Item) => void;
}) {
  const { t } = useTranslation("items");
  const consumeLabel = t("items:actions.consume1unit");
  const actionsLabel = t("items:actions.itemActions");
  // Six cards give six buttons: the name each carries must tell them apart.
  // It still starts with the visible tooltip text (WCAG 2.5.3).
  const actionsName = t("items:actions.itemActionsFor", { name: item.name });
  return (
    <div className="flex flex-col gap-1 flex-shrink-0">
      {/* The words live in a tooltip on hover and on focus, opening to the
          left: the swipe layer clips anything above. On a touch screen the
          row's menu carries these words instead. */}
      {canWrite && (
        <Button
          size="icon"
          variant="ghost"
          onClick={(e) => {
            e.stopPropagation();
            onConsume(item.id);
          }}
          disabled={consumingId === item.id}
          className="relative group/tooltip rounded-xl shadow-none bg-surface-raised text-on-secondary hover:bg-surface-inset hover:text-on"
          aria-label={consumeLabel}
        >
          {consumingId === item.id ? (
            <span className="text-[10px] font-medium">…</span>
          ) : (
            <CheckCircle size={16} />
          )}
          <Tooltip label={consumeLabel} side="left" />
        </Button>
      )}
      <Button
        size="icon"
        variant="ghost"
        onClick={(e) => {
          e.stopPropagation();
          onOpenActions(item);
        }}
        className="relative group/tooltip rounded-xl shadow-none text-on-muted hover:bg-surface-inset hover:text-on"
        aria-label={actionsName}
      >
        <MoreVertical size={16} />
        <Tooltip label={actionsLabel} side="left" />
      </Button>
    </div>
  );
}
