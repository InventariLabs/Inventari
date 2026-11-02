import { useState, useRef, useEffect } from "react";
import { useTranslation } from "react-i18next";
import { RefreshCw, Check } from "lucide-react";
import { Button } from "@/components/ui/Button";
import {
  SELECTABLE_STATUSES,
  STATUS_VARIANT,
  type EquipmentStatus,
} from "@/modules/equipment/components/AssetStatusBadge";
import { cn } from "@/lib/utils";

interface AssetStatusMenuProps {
  /** Current equipment status (drives the highlighted option + button tint).
   *  Null when the asset carries none — there is nothing to highlight and
   *  nothing to list as where they stand, only the choices ahead. */
  currentStatus: EquipmentStatus | null;
  /** Called when the user picks a status. Parent runs the mutation. */
  onChangeStatus: (status: EquipmentStatus) => void;
  /** Disables interaction (e.g. while a request is in flight). */
  disabled?: boolean;
}

/**
 * The statuses this menu may set — SELECTABLE_STATUSES from the badge.
 *
 * "Deployed" and "Retired" are consequences, not choices (see
 * CONSEQUENCE_STATUSES): offering them here produced a row that claimed to be
 * deployed with nobody holding it, and a retirement one click away with no
 * confirmation — the same operation the bulk bar guards with a dialog.
 *
 * MAINTENANCE on a checked-out asset is the third such case: the
 * holder still has the thing and the overview deliberately keeps counting it
 * as deployed (dashboard_service rewrites the count), so the menu used to
 * hand out a status two screens believed and the planner screen ignored.
 * The way into maintenance is checkin → AVAILABLE → MAINTENANCE.
 */

const VARIANT_DOT: Record<
  "success" | "info" | "warning" | "secondary",
  string
> = {
  success: "bg-success-500",
  info: "bg-blue-500",
  warning: "bg-amber-500",
  secondary: "bg-gray-400",
};

/**
 * Compact status changer rendered in the asset detail header.
 *
 * A ghost icon-button (RefreshCw, matching the list-page bulk "Status" action)
 * opens a small dropdown and passes the selected status to the parent. The
 * current status is always listed, even when it is one the menu cannot set,
 * so the reader can see where they stand.
 */
export function AssetStatusMenu({
  currentStatus,
  onChangeStatus,
  disabled,
}: AssetStatusMenuProps) {
  const { t } = useTranslation("equipment");
  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  // On a checked-out asset MAINTENANCE is not offered (see the comment
  // above the component): it is a status the overview refuses to
  // count while someone holds the thing.
  const selectable =
    currentStatus === "DEPLOYED"
      ? SELECTABLE_STATUSES.filter((s) => s !== "MAINTENANCE")
      : SELECTABLE_STATUSES;

  // The current status is always listed, even when it is one the menu
  // cannot set, so the reader can see where they stand — unless there is
  // none, in which case the menu is just the choices ahead.
  const options: EquipmentStatus[] =
    currentStatus == null
      ? selectable
      : selectable.includes(currentStatus)
        ? selectable
        : [currentStatus, ...selectable];

  useEffect(() => {
    if (!open) return;
    const handleClickOutside = (e: MouseEvent) => {
      if (
        containerRef.current &&
        !containerRef.current.contains(e.target as Node)
      ) {
        setOpen(false);
      }
    };
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", handleClickOutside);
    document.addEventListener("keydown", handleKey);
    return () => {
      document.removeEventListener("mousedown", handleClickOutside);
      document.removeEventListener("keydown", handleKey);
    };
  }, [open]);

  return (
    <div className="relative" ref={containerRef}>
      <Button
        variant="ghost"
        size="icon"
        disabled={disabled}
        onClick={() => setOpen((v) => !v)}
        title={t("actions.change_status", "Change status")}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={t("actions.change_status", "Change status")}
      >
        <RefreshCw size={16} />
      </Button>
      {open && (
        <div
          role="menu"
          className="absolute right-0 top-full z-[var(--z-confirm)] mt-1 w-44 overflow-hidden rounded-xl border border-border bg-surface-card py-1 shadow-lg"
        >
          {options.map((status) => {
            const isActive = status === currentStatus;
            const v = STATUS_VARIANT[status];
            return (
              <Button
                size="content"
                key={status}
                type="button"
                variant="ghost"
                role="menuitemradio"
                aria-checked={isActive}
                disabled={isActive}
                onClick={() => {
                  setOpen(false);
                  onChangeStatus(status);
                }}
                className={cn(
                  "w-full justify-start gap-2.5 px-3 py-2 text-sm text-on outline-none",
                  "focus-visible:bg-surface-raised",
                  "disabled:cursor-default disabled:opacity-100 disabled:hover:bg-transparent disabled:pointer-events-auto",
                )}
              >
                <span
                  className={cn(
                    "h-2 w-2 shrink-0 rounded-full",
                    VARIANT_DOT[v],
                  )}
                />
                <span className="flex-1 text-left">
                  {t(`status.${status.toLowerCase()}`, status)}
                </span>
                {isActive && (
                  <Check size={14} className="shrink-0 text-on-primary" />
                )}
              </Button>
            );
          })}
          {/* The missing row explains itself, the way the retire action does:
              without it, Maintenance simply absent from the menu read as a
              status nobody can set, not as one waiting on the return. */}
          {currentStatus === "DEPLOYED" && (
            <p className="mt-1 border-t border-border px-3 pb-1 pt-2 text-xs text-on-muted">
              {t("detail.cannot_maintain_deployed")}
            </p>
          )}
        </div>
      )}
    </div>
  );
}
