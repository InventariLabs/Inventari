import { useTranslation } from "react-i18next";
import type { VariantProps } from "class-variance-authority";

import { Badge, badgeVariants } from "@/components/ui/Badge";
import { cn } from "@/lib/utils";

type BadgeVariant = NonNullable<VariantProps<typeof badgeVariants>["variant"]>;

// Default semantic mapping: common status codes → Badge variants.
const DEFAULT_VARIANTS: Record<string, BadgeVariant> = {
  DRAFT: "secondary",
  PENDING: "warning",
  PENDING_APPROVAL: "warning",
  IN_PROGRESS: "warning",
  MAINTENANCE: "warning",
  ACTIVE: "info",
  DEPLOYED: "info",
  CONFIRMED: "info",
  AVAILABLE: "success",
  COMPLETED: "success",
  APPROVED: "success",
  CANCELLED: "danger",
  REJECTED: "danger",
  RETIRED: "danger",
};

interface StatusBadgeProps {
  /** Null names an absence: nothing was ever recorded, and the badge says
   *  whatever `labelKey` says rather than a name. */
  status: string | null;
  /** i18n namespace (module-local translations). */
  ns?: string;
  /** Override the variant lookup. Merges with defaults. */
  variants?: Record<string, BadgeVariant>;
  /** Variant to use when status is not in the map. */
  fallbackVariant?: BadgeVariant;
  /** Explicit label text — skips i18n entirely. */
  label?: string;
  /** Full i18n key for the label — skips the `status.${status.toLowerCase()}` key construction. */
  labelKey?: string;
  /** Override the label key prefix (default: "status"). Key becomes `status.${status.toLowerCase()}`. */
  labelKeyPrefix?: string;
  className?: string;
}

export function StatusBadge({
  status,
  ns,
  variants,
  fallbackVariant = "secondary",
  label,
  labelKey,
  labelKeyPrefix = "status",
  className,
}: StatusBadgeProps) {
  const { t } = useTranslation(ns ? [ns, "common"] : ["common"]);
  const merged = { ...DEFAULT_VARIANTS, ...variants };
  const variant =
    (status != null ? merged[status] : undefined) ?? fallbackVariant;
  const key = labelKey ?? `${labelKeyPrefix}.${status?.toLowerCase() ?? ""}`;
  const translated = t(key, { defaultValue: status ?? "" });
  // i18next returns the key itself when a translation is missing; treat that
  // as "not found" and fall back to the raw status text.
  const displayLabel =
    label ?? (translated === key ? (status ?? "") : translated);
  return (
    // A status is one of the two roles uppercase is kept for (the other is a
    // column header): it is a fixed vocabulary the reader learns to recognise
    // by shape, not a phrase they read.
    <Badge
      variant={variant}
      className={cn("uppercase tracking-widest", className)}
    >
      {displayLabel}
    </Badge>
  );
}
