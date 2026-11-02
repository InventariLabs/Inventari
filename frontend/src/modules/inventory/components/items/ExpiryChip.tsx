import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { Calendar } from "lucide-react";

import { Badge } from "@/components/ui/Badge";
import { effectiveExpiry } from "@/utils/effectiveExpiry";
import { formatDate, getExpiryState } from "@/utils/helpers";
import { EXPIRY_BADGE_VARIANT } from "./expiryBadge";

/**
 * The expiry date of a record as a coloured badge, judged by the date that
 * counts: the batch's own or, if earlier, the use-by given when the package
 * was opened. Shows `fallback` (nothing by default) when there is no date.
 */
export default function ExpiryChip({
  item,
  compact = false,
  fallback = null,
}: {
  item: { expiry_date?: string | null; effective_expiry_date?: string | null };
  compact?: boolean;
  fallback?: ReactNode;
}) {
  const { t } = useTranslation(["items"]);
  const date = effectiveExpiry(item);
  if (!date) return <>{fallback}</>;
  const state = getExpiryState(date);
  return (
    <Badge
      variant={EXPIRY_BADGE_VARIANT[state]}
      className={
        compact ? "gap-1 px-1.5 py-0" : "gap-1.5 px-2 py-1 text-[10px]"
      }
      data-testid="item-expiry"
      data-expiry-state={state}
    >
      <Calendar size={compact ? 10 : 12} />
      <span>{formatDate(date, t)}</span>
    </Badge>
  );
}
