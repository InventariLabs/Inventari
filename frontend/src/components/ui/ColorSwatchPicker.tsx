import { useTranslation } from "react-i18next";
import { Check } from "lucide-react";
import { cn } from "@/lib/utils";
import { FALLBACK_COLORS, type CategoryColorKey } from "./CategoryAvatar";

export interface ColorSwatchPickerProps {
  /** Currently selected palette key, or null for "auto" (hash fallback). */
  value: string | null;
  /** Called with the new value. Pass null to clear (use hash fallback). */
  onChange: (color: string | null) => void;
  className?: string;
  /** Allow opting out of the picker (e.g. quick-create modals). */
  showAuto?: boolean;
}

/** Saturated fill per key so the hue reads clearly at 24 px — the
 *  avatar itself renders a soft tint of the same hue. Static literals:
 *  Tailwind 3 only generates classes it can see. */
const SWATCH_STYLES: Record<string, { bg: string; active: string }> = {
  accent: { bg: "bg-accent-400", active: "ring-accent-600" },
  sky: { bg: "bg-sky-400", active: "ring-sky-600" },
  violet: { bg: "bg-violet-400", active: "ring-violet-600" },
  amber: { bg: "bg-amber-400", active: "ring-amber-600" },
  rose: { bg: "bg-rose-400", active: "ring-rose-600" },
  teal: { bg: "bg-teal-400", active: "ring-teal-600" },
  slate: { bg: "bg-slate-400", active: "ring-slate-600" },
  // Legacy keys — not offered, but shown when already stored.
  purple: { bg: "bg-purple-400", active: "ring-purple-600" },
  pink: { bg: "bg-pink-400", active: "ring-pink-600" },
  indigo: { bg: "bg-indigo-400", active: "ring-indigo-600" },
};

/** Every palette key this picker can render — the set the catalogues must name. */
export const PALETTE_KEYS: string[] = Object.keys(SWATCH_STYLES);

/**
 * Inline row of color swatches for category forms. Offers the curated
 * ``FALLBACK_COLORS`` set (kept in sync with CategoryAvatar). A stored
 * legacy key (purple/pink/indigo) still renders its swatch appended at
 * the end so the current selection is never invisible.
 *
 * The "Auto" option clears the ``color`` field so the renderer falls
 * back to a hash of the category name (consistent color per name).
 *
 * **What a swatch is called.** The palette is a design-system token
 * (`sky`, `slate`, `accent`), and those keys used to be the buttons'
 * accessible names — a screen reader announced "slate" in a Polish
 * dialog, and `accent` is not even a colour but a role. The names live in
 * the catalogue instead, under ``modal.colors.<key>``, one per language:
 * `accent` is named after the role it plays ("Primary"), the rest after
 * the colour a person sees. A key added to the palette needs its name
 * there — `ColorSwatchPicker.test.tsx` fails on a palette key the
 * catalogues do not name.
 *
 * Below `md` each swatch keeps a 44px touch target with the dot itself
 * still 24px inside it (UI_GUIDELINES §2.10): the row offers eight
 * adjacent colours, and at 24px the gap between neighbours was smaller
 * than a thumb.
 */
export function ColorSwatchPicker({
  value,
  onChange,
  className,
  showAuto = true,
}: ColorSwatchPickerProps) {
  const { t } = useTranslation("categories");
  const isCuratedKey = (k: string | null): k is CategoryColorKey =>
    !!k && (FALLBACK_COLORS as readonly string[]).includes(k);
  const isKnownKey = (k: string | null): k is string =>
    !!k && k in SWATCH_STYLES;

  const swatchKeys: string[] = [...FALLBACK_COLORS];
  if (value && isKnownKey(value) && !isCuratedKey(value)) {
    swatchKeys.push(value);
  }

  return (
    <div
      className={cn("flex flex-wrap items-center gap-2", className)}
      role="radiogroup"
      aria-label={t("modal.colorLabel", { defaultValue: "Color" })}
    >
      {showAuto ? (
        <button
          type="button"
          role="radio"
          aria-checked={value === null}
          onClick={() => onChange(null)}
          className={cn(
            "flex h-11 items-center justify-center rounded-full border px-2.5 text-xs font-medium transition-colors md:h-6",
            value === null
              ? "border-accent-600 bg-accent-100 text-accent-700 ring-2 ring-accent-200"
              : "border-border bg-surface text-on-secondary hover:bg-surface-raised",
          )}
          title={t("modal.colorAuto", { defaultValue: "Auto" })}
        >
          {value === null && <Check size={11} className="mr-1" />}
          {t("modal.colorAuto", { defaultValue: "Auto" })}
        </button>
      ) : null}
      {swatchKeys.map((key) => {
        const isActive = value === key;
        const styles = SWATCH_STYLES[key];
        const name = t(`modal.colors.${key}`);
        return (
          <button
            key={key}
            type="button"
            role="radio"
            aria-checked={isActive}
            onClick={() => onChange(key)}
            className="group flex h-11 w-11 items-center justify-center rounded-full md:h-6 md:w-6"
            aria-label={name}
            title={name}
          >
            <span
              aria-hidden="true"
              className={cn(
                "h-6 w-6 rounded-full transition-transform group-hover:scale-110",
                styles.bg,
                isActive
                  ? cn("ring-2 ring-offset-2", styles.active)
                  : "opacity-70 group-hover:opacity-100",
              )}
            />
          </button>
        );
      })}
    </div>
  );
}
