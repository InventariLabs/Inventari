import * as React from "react";
import * as PopoverPrimitive from "@radix-ui/react-popover";
import { MoreHorizontal } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Z_TIER_TO_VAR, type SheetZTier } from "@/components/ui/Sheet";
import { cn } from "@/lib/utils";

/**
 * The "⋯" overflow menu: actions that belong to a record rather than to what
 * the user is doing to it right now.
 *
 * A form footer speaks about the current edit — save it, abandon it. Deleting
 * or archiving speaks about the record, and lives past the dialog that opened
 * it. Those two scopes do not share a row, so the record's actions come here,
 * beside the close button, and the footer keeps a single row (§4.3).
 *
 * Ordering is the component's job, not the call site's: non-destructive
 * actions first, then a separator, then the destructive ones. A call site that
 * has to remember the order gets it wrong on the screen nobody re-checks.
 *
 * Built on Popover rather than a dropdown primitive because that is the one
 * this project already depends on. `Sheet` is hand-rolled rather than a Radix
 * modal dialog, so a popover inside it stays interactive — a portal under a
 * modal Radix dialog does not.
 *
 * An action that opens a window of its own sets state in the caller and the
 * caller renders the window beside the menu, never inside it. The popper
 * wrapper carries a `transform`, which turns it into the containing block of
 * anything `position: fixed` within — a sheet mounted in the menu was laid
 * out against the 224 px menu instead of the screen — and the menu unmounting
 * on close would take the window with it. The menu takes no children for
 * that reason.
 */
export interface ActionMenuAction {
  /** Stable identity for React and for tests. */
  id: string;
  label: string;
  icon?: React.ReactNode;
  onSelect: () => void;
  disabled?: boolean;
  /** Danger colour, and placed after the separator regardless of input order. */
  destructive?: boolean;
  /**
   * Extra classes for the row — `sm:hidden` for an action that has a button of
   * its own from `sm` up and only needs the menu on a phone.
   */
  className?: string;
}

/**
 * `popover` is the layer for a menu anchored on ordinary page content. A menu
 * whose trigger lives inside a sheet has to name that sheet's tier instead,
 * or it opens behind the surface that owns it.
 */
export type ActionMenuLayer = "popover" | SheetZTier;

const LAYER_TO_VAR: Record<ActionMenuLayer, string> = {
  popover: "var(--z-popover)",
  ...Z_TIER_TO_VAR,
};

export interface ActionMenuProps {
  actions: ActionMenuAction[];
  /** Accessible name of the trigger — say which record the menu acts on. */
  label: string;
  align?: "start" | "center" | "end";
  layer?: ActionMenuLayer;
  triggerClassName?: string;
  contentClassName?: string;
}

export function ActionMenu({
  actions,
  label,
  align = "end",
  layer = "popover",
  triggerClassName,
  contentClassName,
}: ActionMenuProps) {
  const [open, setOpen] = React.useState(false);
  const close = React.useCallback(() => setOpen(false), []);

  // Every surface this menu opens on — `Sheet`, `ItemEditModal` — closes
  // itself on Escape from its own `document` listener, registered when the
  // surface mounted and therefore ahead of the menu's. Without this, one press
  // takes down the editor along with the menu. The capture phase runs before
  // any of those listeners, so stopping propagation there leaves the menu the
  // only thing that closes.
  React.useEffect(() => {
    if (!open) return;
    const handleEscape = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      event.stopPropagation();
      setOpen(false);
    };
    document.addEventListener("keydown", handleEscape, true);
    return () => document.removeEventListener("keydown", handleEscape, true);
  }, [open]);

  const ordered = [
    ...actions.filter((action) => !action.destructive),
    ...actions.filter((action) => action.destructive),
  ];
  const separatorBefore = ordered.some((action) => !action.destructive)
    ? ordered.find((action) => action.destructive)?.id
    : undefined;

  return (
    <PopoverPrimitive.Root open={open} onOpenChange={setOpen}>
      <PopoverPrimitive.Trigger asChild>
        <Button
          variant="ghost"
          size="icon"
          aria-label={label}
          title={label}
          className={cn("text-on-muted hover:text-on", triggerClassName)}
        >
          <MoreHorizontal size={18} />
        </Button>
      </PopoverPrimitive.Trigger>
      <PopoverPrimitive.Portal>
        <PopoverPrimitive.Content
          align={align}
          sideOffset={4}
          style={{ zIndex: LAYER_TO_VAR[layer] }}
          className={cn(
            "w-56 bg-surface-card rounded-xl border border-border shadow-xl p-1 flex flex-col gap-1",
            contentClassName,
          )}
        >
          {ordered.map((action) => (
            <React.Fragment key={action.id}>
              {separatorBefore === action.id && (
                <div role="separator" className="my-1 h-px bg-border" />
              )}
              <Button
                variant="ghost"
                disabled={action.disabled}
                onClick={() => {
                  close();
                  action.onSelect();
                }}
                className={cn(
                  "w-full justify-start gap-2",
                  action.destructive
                    ? "text-on-danger hover:text-on-danger hover:bg-red-100"
                    : "text-on-secondary hover:text-on",
                  action.className,
                )}
              >
                {action.icon}
                {action.label}
              </Button>
            </React.Fragment>
          ))}
        </PopoverPrimitive.Content>
      </PopoverPrimitive.Portal>
    </PopoverPrimitive.Root>
  );
}
