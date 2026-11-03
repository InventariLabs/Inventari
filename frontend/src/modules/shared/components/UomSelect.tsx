import React, { useEffect, useState } from "react";
import * as PopoverPrimitive from "@radix-ui/react-popover";
import { X, Check, ChevronDown } from "lucide-react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/Button";
import { InlineQueryError } from "@/components/ui/QueryResult";
import { useUoms } from "@/modules/shared/hooks/useUoms";
import { useTranslation } from "react-i18next";
import type { UseQueryResult } from "@tanstack/react-query";
import type { Uom, UomCategory } from "@/types";
import {
  readJson,
  registerOverlaySheet,
  useFocusTrap,
  writeJson,
} from "@/module-sdk";
import { unitLabel } from "@/lib/i18nHelpers";

interface UomSelectProps {
  value: string | null;
  onChange: (uomId: string, uom: Uom) => void;
  error?: string;
  className?: string;
  disabled?: boolean;
  compact?: boolean;
  /** Render the picker as an inline popover under the trigger instead of a modal sheet. */
  inline?: boolean;
  /** Restrict the choices to these UoM categories (e.g. ["Weight"] for a
   * weight field, where offering pieces would make no sense). */
  categoryFilter?: string[];
  /**
   * Restrict the choices to units convertible into this one (same category).
   * Several ids widen the list to every one of their categories — a stock
   * unit that is a piece plus the weight stated per piece.
   *
   * For fields where the value has to be readable as another unit — a recipe
   * line, whose quantity the maker converts into the ingredient's stock unit
   * — offering units the guard will refuse is offering an error. The caller
   * passes the unit the value has to be readable as; the same rule the
   * server enforces (same category ⇒ convertible) decides the list.
   */
  convertibleTo?: string | string[] | null;
  /** Said under the picker when `convertibleTo` narrows the choices, so a
   * missing unit reads as a rule rather than as a missing catalogue row. */
  convertibleHint?: string;
  /**
   * The unit a save lands on when nobody picks one, for a form whose server
   * answers that itself. The compact trigger shows it as chosen: "Choose"
   * beside a form that then saved pieces read as a question still open.
   */
  unitWhenUnset?: string;
}

// ── What to show (symbols in preferred display order) ────────────────────────
// Only units that actually exist in DB seeding are listed here.
// Common = shown by default in the flat grid.
// Rare = shown after "More options".
const COMMON_ORDER = ["g", "kg", "ml", "l", "pcs", "pack"];
const RARE_ORDER = [
  "mg",
  "oz",
  "lb",
  "cup",
  "fl oz",
  "pt",
  "qt",
  "gal",
  "m",
  "cm",
];

// ── Chip ─────────────────────────────────────────────────────────────────────
const UomChip: React.FC<{
  uom: Uom;
  selected: boolean;
  onClick: () => void;
  tName: string;
  tSymbol: string;
}> = ({ selected, onClick, tName, tSymbol }) => (
  <Button
    size="content"
    type="button"
    variant="ghost"
    onClick={onClick}
    className={cn(
      "relative flex-col gap-0.5 select-none rounded-xl border active:scale-95",
      "py-2.5 px-1 w-full h-[3.25rem]",
      selected
        ? "border-primary-500 bg-primary-50 text-primary-700 shadow-sm shadow-primary-100"
        : "border-border bg-surface-card text-on-secondary hover:border-border hover:bg-surface",
    )}
  >
    {selected && (
      <span className="absolute top-0.5 right-1">
        <Check size={9} strokeWidth={3} className="text-primary-500" />
      </span>
    )}
    <span className="text-sm font-semibold leading-none">{tSymbol}</span>
    <span className="text-[10px] leading-tight text-on-secondary truncate w-full text-center px-0.5">
      {tName}
    </span>
  </Button>
);

// ── Recently used (localStorage) ─────────────────────────────────────────────
const RECENT_KEY = "inventari:recentUomIds";
const MAX_RECENT = 4;

/** The wire leaves `uoms` optional on a category; a category without any has none. */
function uomsOf(category: UomCategory): Uom[] {
  return category.uoms ?? [];
}

/** The categories a `convertibleTo` keeps, or null when it names none. */
function convertibleCategories(
  categories: UomCategory[] | undefined,
  convertibleTo: string | string[] | null | undefined,
): Set<string> | null {
  const ids = [convertibleTo ?? []].flat();
  const kept = categories
    ?.flatMap(uomsOf)
    .filter((u) => ids.includes(u.id))
    .map((u) => u.category_id);
  return kept?.length ? new Set(kept) : null;
}

function loadRecentIds(): string[] {
  return readJson<string[]>(RECENT_KEY, []);
}
function saveRecentId(id: string): void {
  const prev = loadRecentIds().filter((x) => x !== id);
  writeJson(RECENT_KEY, [id, ...prev].slice(0, MAX_RECENT));
}

// ── Helper: render a flat 4-column grid of chips ──────────────────────────
const ChipGrid: React.FC<{
  uoms: Uom[];
  value: string | null;
  onSelect: (uom: Uom) => void;
}> = ({ uoms, value, onSelect }) => {
  const { t } = useTranslation(["items"]);
  return (
    <div className="grid grid-cols-4 gap-2">
      {uoms.map((uom) => (
        <UomChip
          key={uom.id}
          uom={uom}
          selected={uom.id === value}
          onClick={() => onSelect(uom)}
          tName={t(`items:uomNames.${uom.name}`, { defaultValue: uom.name })}
          tSymbol={unitLabel(t, uom.symbol)}
        />
      ))}
    </div>
  );
};

// A failed units request leaves the picker with nothing to offer, which reads
// as a catalogue without units. Say it did not load, and offer a retry.
const UomsLoadFailed: React.FC<{
  query: Pick<UseQueryResult, "isError" | "error" | "refetch">;
}> = ({ query }) =>
  query.isError ? (
    <div className="mt-1.5">
      <InlineQueryError
        error={query.error}
        onRetry={() => void query.refetch()}
      />
    </div>
  ) : null;

// ── Main ──────────────────────────────────────────────────────────────────────
export const UomSelect: React.FC<UomSelectProps> = ({
  value,
  onChange,
  error,
  className,
  disabled,
  compact,
  inline,
  categoryFilter,
  convertibleTo,
  convertibleHint,
  unitWhenUnset,
}) => {
  const { t } = useTranslation(["items", "common"]);
  const uomsQuery = useUoms();
  const { data: categories, isLoading } = uomsQuery;
  const [isOpen, setIsOpen] = useState(false);
  const [showMore, setShowMore] = useState(false);
  const [recentIds, setRecentIds] = useState<string[]>(loadRecentIds);
  const panelRef = useFocusTrap(isOpen);

  const close = () => {
    setIsOpen(false);
    setShowMore(false);
  };

  // The inline popover leaves on Escape through Radix; the modal sheet is
  // ours to close. It takes part in the overlay stack, so a form sheet under
  // it stands idle on the press aimed at the picker instead of closing too
  // and taking what was typed with it.
  useEffect(() => {
    if (!isOpen || inline) return;
    const layer = registerOverlaySheet(panelRef.current);
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      setIsOpen(false);
      setShowMore(false);
    };
    document.addEventListener("keydown", onKey);
    return () => {
      layer.release();
      document.removeEventListener("keydown", onKey);
    };
  }, [isOpen, inline, panelRef]);

  // Convertibility is sameness of category, the rule `core_api.uoms.
  // convert_quantity` applies on the server: a line in another kind of unit
  // can never be read as the stock unit, so it is not offered here.
  const restricted = convertibleCategories(categories, convertibleTo);

  const allUoms =
    categories
      ?.filter(
        (uomGroup) => !categoryFilter || categoryFilter.includes(uomGroup.name),
      )
      .flatMap(uomsOf)
      .filter((u) => restricted === null || restricted.has(u.category_id)) ??
    [];
  const selectedUom = allUoms.find((u) => u.id === value);

  // Build ordered arrays from COMMON_ORDER / RARE_ORDER
  const commonUoms = COMMON_ORDER.map((sym) =>
    allUoms.find((u) => u.symbol === sym),
  ).filter((u): u is Uom => Boolean(u));
  const rareUoms = RARE_ORDER.map((sym) =>
    allUoms.find((u) => u.symbol === sym),
  ).filter((u): u is Uom => Boolean(u));
  const recentUoms = recentIds
    .map((id) => allUoms.find((u) => u.id === id))
    .filter((u): u is Uom => Boolean(u));
  const recentIdsSet = new Set(recentUoms.map((u) => u.id));
  const commonFiltered = commonUoms.filter((u) => !recentIdsSet.has(u.id));

  const handleSelect = (uom: Uom) => {
    saveRecentId(uom.id);
    setRecentIds(loadRecentIds());
    onChange(uom.id, uom);
    setIsOpen(false);
    setShowMore(false);
  };

  const loadError = <UomsLoadFailed query={uomsQuery} />;

  // ── Trigger button ────────────────────────────────────────────────────────
  const trigger = compact ? (
    <Button
      type="button"
      variant="outline"
      disabled={disabled || isLoading}
      onClick={() => setIsOpen(true)}
      className={cn(
        // One border weight for every control (UI_GUIDELINES §2.10): at 2px
        // this trigger drew a visibly heavier box than the quantity and price
        // fields on the same line. Emphasis is colour, not thickness.
        "w-full justify-between gap-1.5 px-3 py-0",
        "border rounded-lg outline-none",
        error
          ? "border-red-300"
          : value
            ? "border-primary-500 bg-primary-50"
            : "border-border",
        className,
      )}
    >
      {/* The compact trigger shows only the symbol — once an em dash, which
          was the control's whole name: "dash, button". The field's name
          leads, read but not shown, and the shown symbol stays in the name:
          an `aria-label` of "Unit" alone replaced it, so a voice user saying
          "pcs" reached nothing (WCAG 2.5.3). */}
      <span className="sr-only">{t("items:form.unitLabel")}</span>{" "}
      <span
        className={cn(
          "text-xs font-medium",
          value || unitWhenUnset ? "text-primary-700" : "text-on-muted",
        )}
      >
        {selectedUom || unitWhenUnset
          ? unitLabel(t, selectedUom?.symbol ?? unitWhenUnset)
          : // A dash beside a sibling picker reading "pcs" says nothing
            // about whether the unit is unset or does not apply. A verb, and
            // one that is not also the name of a unit: every other value this
            // control ever shows is a unit symbol, so "Set" read as "a set".
            t("items:form.unitEmpty", { defaultValue: "Choose" })}
      </span>
      <ChevronDown
        size={14}
        className={
          value || unitWhenUnset ? "text-primary-500" : "text-on-muted"
        }
      />
    </Button>
  ) : (
    <Button
      size="content"
      type="button"
      variant="outline"
      disabled={disabled || isLoading}
      onClick={() => setIsOpen(true)}
      className={cn(
        "w-full justify-between gap-3 px-4 py-2.5",
        "border rounded-lg outline-none text-left",
        error
          ? "border-red-300 text-red-900"
          : value
            ? "border-primary-500 text-primary-700"
            : "border-border text-on-muted",
        className,
      )}
    >
      {selectedUom ? (
        <span className="flex items-center gap-2 font-semibold text-on">
          <span className="inline-flex items-center justify-center w-6 h-6 rounded-md bg-primary-100 text-primary-700 text-xs font-medium shrink-0">
            {unitLabel(t, selectedUom.symbol)}
          </span>
          {t(`items:uomNames.${selectedUom.name}`, {
            defaultValue: selectedUom.name,
          })}
        </span>
      ) : (
        <span>
          {isLoading
            ? t("common:messages.loading")
            : t("items:form.selectUnit", {
                defaultValue: "Select unit...",
              })}
        </span>
      )}
      <ChevronDown
        size={16}
        className={value ? "text-primary-500" : "text-on-muted"}
      />
    </Button>
  );

  // ── Panel content (shared by modal sheet and inline popover) ───────────────
  const panelContent = (
    <>
      {/* Recently used */}
      {recentUoms.length > 0 && (
        <div>
          <p className="text-xs font-medium text-on-muted mb-2">
            {t("items:uom.recentlyUsed", {
              defaultValue: "Recently used",
            })}
          </p>
          <ChipGrid uoms={recentUoms} value={value} onSelect={handleSelect} />
        </div>
      )}

      {/* All common units – single flat 4-col grid, no category headers */}
      <ChipGrid uoms={commonFiltered} value={value} onSelect={handleSelect} />

      {/* More options toggle */}
      <Button
        size="content"
        type="button"
        variant="ghost"
        onClick={() => setShowMore((v) => !v)}
        className="w-full justify-center gap-1.5 py-1.5 border border-dashed border-border text-xs font-medium text-on-muted hover:text-on-secondary hover:border-border"
      >
        <ChevronDown
          size={13}
          className={cn("transition-transform", showMore && "rotate-180")}
        />
        {showMore
          ? t("common:actions.lessOptions", {
              defaultValue: "Fewer options",
            })
          : t("common:actions.moreOptions")}
      </Button>

      {/* Rare / imperial units */}
      {showMore && rareUoms.length > 0 && (
        <div className="animate-in fade-in slide-in-from-top-2 duration-200">
          <ChipGrid uoms={rareUoms} value={value} onSelect={handleSelect} />
        </div>
      )}
    </>
  );

  // Inline mode: Radix Popover with Portal. The panel used to be
  // positioned `absolute` inside the trigger wrapper, so overflowing rows
  // clipped it (the fixed click-catcher backdrop escaped the clip but merely
  // closed the panel). The portal escapes the clipping containers, and
  // Popover handles outside clicks, Escape and collision-free positioning.
  if (inline) {
    return (
      <PopoverPrimitive.Root
        open={isOpen}
        onOpenChange={(open) => (open ? setIsOpen(true) : close())}
      >
        <PopoverPrimitive.Trigger asChild>{trigger}</PopoverPrimitive.Trigger>
        <PopoverPrimitive.Portal>
          <PopoverPrimitive.Content
            className="z-[var(--z-popover)] w-72 max-w-[calc(100vw-2rem)] bg-surface-card rounded-2xl border border-border shadow-xl animate-in fade-in zoom-in-95 duration-150 flex flex-col max-h-80 overflow-hidden"
            sideOffset={4}
          >
            <div className="flex items-center justify-between px-4 py-2.5 border-b border-border shrink-0">
              <h3 className="text-sm font-semibold text-on">
                {t("items:itemUnit", { defaultValue: "Unit" })}
              </h3>
              <Button
                type="button"
                variant="ghost"
                size="iconSm"
                onClick={close}
                aria-label={t("common:actions.close")}
                className="rounded-full text-on-muted"
              >
                <X size={16} />
              </Button>
            </div>
            <div className="overflow-y-auto flex-1 px-4 pt-3 pb-4 space-y-3">
              {panelContent}
            </div>
          </PopoverPrimitive.Content>
        </PopoverPrimitive.Portal>
        {loadError}
        {restricted !== null && convertibleHint && (
          <p
            className="text-xs text-on-muted mt-1.5"
            data-testid="uom-convertible-hint"
          >
            {convertibleHint}
          </p>
        )}
        {error && (
          <p className="text-xs text-red-600 mt-1.5 font-medium">{error}</p>
        )}
      </PopoverPrimitive.Root>
    );
  }

  return (
    <div>
      {trigger}
      {loadError}
      {restricted !== null && convertibleHint && (
        <p
          className="text-xs text-on-muted mt-1.5"
          data-testid="uom-convertible-hint"
        >
          {convertibleHint}
        </p>
      )}
      {error && (
        <p className="text-xs text-red-600 mt-1.5 font-medium">{error}</p>
      )}

      {isOpen && (
        <div
          className="fixed inset-0 !m-0 z-50 flex items-end sm:items-center justify-center"
          role="dialog"
          aria-modal="true"
          aria-label={t("items:itemUnit", { defaultValue: "Unit" })}
        >
          {/* Backdrop */}
          <div
            className="absolute inset-0 bg-black/50 backdrop-blur-sm animate-in fade-in duration-200"
            onClick={close}
          />

          {/* Sheet */}
          <div
            ref={panelRef}
            className="relative w-full sm:max-w-sm bg-surface-card rounded-t-3xl sm:rounded-2xl shadow-2xl animate-in slide-in-from-bottom sm:zoom-in-95 duration-300 mb-16 sm:mb-0 flex flex-col"
            style={{ maxHeight: "calc(85vh - 4rem)" }}
          >
            {/* Handle */}
            <div className="flex justify-center pt-3 pb-0.5 sm:hidden shrink-0">
              <div className="w-10 h-1 rounded-full bg-surface-inset" />
            </div>

            {/* Header */}
            <div className="flex items-center justify-between px-5 py-3 border-b border-border shrink-0">
              <h3 className="text-base font-semibold text-on">
                {t("items:itemUnit", { defaultValue: "Unit" })}
              </h3>
              <Button
                type="button"
                variant="ghost"
                size="iconSm"
                onClick={close}
                aria-label={t("common:actions.close")}
                className="rounded-full text-on-muted"
              >
                <X size={18} />
              </Button>
            </div>

            {/* Content */}
            <div className="overflow-y-auto flex-1 px-5 pt-4 pb-5 space-y-4">
              {panelContent}
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
