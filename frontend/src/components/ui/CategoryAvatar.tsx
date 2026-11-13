import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import { categoryLabel } from "@/lib/i18nHelpers";
import { cn } from "@/lib/utils";
import { FluentEmoji } from "./FluentEmoji";
import { resolveCategoryEmoji } from "@/lib/categoryEmoji";

/**
 * Tailwind palette keys that may appear in ``Category.color`` (user override)
 * or be derived via the hash fallback. Each maps to a set of
 * background / foreground / border classes. Keep this list in sync with
 * the choices offered in the color picker and the backend
 * ``color`` column documentation.
 *
 * Why palette KEYS, not hex values? Tailwind's JIT purges any class not
 * present in source. ``bg-[#abc123]`` would be stripped; ``bg-indigo-100``
 * is statically referenceable and survives.
 */
export const FALLBACK_COLORS = [
  "accent",
  "sky",
  "violet",
  "amber",
  "rose",
  "teal",
  "slate",
] as const;
export type CategoryColorKey = (typeof FALLBACK_COLORS)[number];

/** Palette keys stored by older deployments. Still rendered, but no
 *  longer offered in pickers or used by the name-hash fallback —
 *  purple/indigo and pink/rose read as twins at small sizes, which is
 *  why the curated set replaced them. */
const LEGACY_COLOR_KEYS = ["purple", "pink", "indigo"] as const;
type LegacyColorKey = (typeof LEGACY_COLOR_KEYS)[number];

/** Static class map — Tailwind 3 scans sources for literals, so the
 *  previous `bg-${key}-100` template string only worked by accident.
 *  Every class below must stay a literal. */
const COLOR_CLASSES: Record<CategoryColorKey | LegacyColorKey, string> = {
  accent: "bg-accent-100 text-accent-700 border-accent-200",
  sky: "bg-sky-100 text-sky-700 border-sky-200",
  violet: "bg-violet-100 text-violet-700 border-violet-200",
  amber: "bg-amber-100 text-amber-800 border-amber-200",
  rose: "bg-rose-100 text-rose-700 border-rose-200",
  teal: "bg-teal-100 text-teal-700 border-teal-200",
  // ui-pattern: palette-identity — slate is one of the colours the user picks
  // for a category, a named identity and not the product's neutral grey.
  slate: "bg-slate-100 text-slate-700 border-slate-200",
  purple: "bg-purple-100 text-purple-700 border-purple-200",
  pink: "bg-pink-100 text-pink-700 border-pink-200",
  indigo: "bg-indigo-100 text-indigo-700 border-indigo-200",
};

function isKnownColorKey(
  key: string,
): key is CategoryColorKey | LegacyColorKey {
  return key in COLOR_CLASSES;
}

/** Resolve the background / text / border Tailwind classes for a given
 *  palette key. */
function colorClasses(key: CategoryColorKey | LegacyColorKey): string {
  return COLOR_CLASSES[key];
}

/** Hash a string into a stable index in [0, mod). Mirrors the legacy
 *  CategoryAvatar behavior so existing users see no visual change for
 *  categories that have neither ``color`` nor ``category_type``. */
function hashName(name: string): number {
  let h = 0;
  for (let i = 0; i < name.length; i++) {
    h = name.charCodeAt(i) + ((h << 5) - h);
  }
  return Math.abs(h);
}

export interface CategoryAvatarCategory {
  /** User-overridable single-glyph emoji (e.g. "🥚"). */
  emoji?: string | null;
  /** User-overridable Tailwind palette key (e.g. "indigo"). */
  color?: string | null;
  /** Used as the seed for the keyword-guess cascade and the color hash. */
  name?: string | null;
  /** Optional code, also used as cascade input. */
  code?: string | null;
  /** Vertical context (e.g. "equipment", "food"). */
  contextTag?: string | null;
}

export interface CategoryAvatarProps {
  /** The full category object. Symbol + color are derived from this. */
  category: CategoryAvatarCategory;
  /** "sm" = 24 px, "md" = 32 px, "lg" = 48 px. Default "md". */
  size?: "sm" | "md" | "lg";
  /** When true, renders the category name to the right of the avatar. */
  showName?: boolean;
  shape?: "circle" | "square";
  className?: string;
}

const SIZE_PX: Record<NonNullable<CategoryAvatarProps["size"]>, number> = {
  sm: 24,
  md: 32,
  lg: 48,
};

/**
 * Decorative visual identity for a category — emoji + soft tinted background.
 * Pair with a category caption, or use showName to render one.
 *
 * Replaces the legacy 2-letter initials which collapsed to noise
 * (the "EE × 13" collision in the e2e test DB). The symbol cascade lives
 * in `resolveCategoryEmoji` (lib/categoryEmoji.ts).
 */
export function CategoryAvatar({
  category,
  size = "md",
  showName = false,
  shape = "circle",
  className,
}: CategoryAvatarProps) {
  const pixelSize = SIZE_PX[size];
  const { t } = useTranslation();

  const { emoji, classes, displayName } = useMemo(() => {
    const resolved = resolveCategoryEmoji({
      emoji: category.emoji,
      name: category.name,
      code: category.code,
      contextTag: category.contextTag,
    });

    // Color resolution order:
    //   1. user-set category.color (curated key or still-supported legacy key)
    //   2. hash(category.name) → curated FALLBACK_COLORS
    //
    // A third step used to sit between them: a map from the deprecated
    // `category_type` to a fixed tint, which is domain knowledge — three food
    // storage codes — inside a generic Design System component. It also
    // painted every category of one type the same colour, which is the
    // opposite of what an identity avatar is for. The property and the hash
    // decide now.
    let key: CategoryColorKey | LegacyColorKey;
    const userKey = category.color;
    if (userKey && isKnownColorKey(userKey)) {
      key = userKey;
    } else {
      const idx = hashName(category.name ?? "") % FALLBACK_COLORS.length;
      key = FALLBACK_COLORS[idx];
    }

    return {
      emoji: resolved,
      classes: colorClasses(key),
      // The tooltip uses the category's localized name too,
      // so they speak the reader's language like the label beside them.
      // The colour hash above keeps the record's own name: a tint that
      // changed with the language would not be an identity.
      displayName: categoryLabel(t, category.code, category.name ?? ""),
    };
  }, [category, t]);

  const radiusClass = shape === "circle" ? "rounded-full" : "rounded-xl";

  return (
    <div
      className={cn("inline-flex items-center gap-2", className)}
      data-testid="category-avatar"
    >
      <div
        className={cn(
          "flex items-center justify-center border border-b-2 shadow-sm",
          radiusClass,
          classes,
        )}
        style={{
          width: pixelSize,
          height: pixelSize,
          minWidth: pixelSize,
          minHeight: pixelSize,
        }}
        title={displayName}
        aria-hidden="true"
      >
        <FluentEmoji emoji={emoji} size={Math.round(pixelSize * 0.7)} />
      </div>
      {showName && displayName ? (
        <span className="text-sm font-medium text-on truncate">
          {displayName}
        </span>
      ) : null}
    </div>
  );
}
