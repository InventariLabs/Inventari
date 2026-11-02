import * as PopoverPrimitive from "@radix-ui/react-popover";
import { cn } from "@/lib/utils";

interface InlinePopoverProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** The control the panel hangs off. Rendered as the Radix trigger. */
  trigger: React.ReactNode;
  children: React.ReactNode;
  align?: "start" | "center" | "end";
  className?: string;
}

/**
 * A small panel anchored to a control, on the system layer.
 *
 * The module grew three hand-rolled versions of this — a `fixed inset-0 z-40`
 * backdrop plus an `absolute … z-50` panel — and each one repeated the same two
 * defects. The z-indexes are arbitrary numbers outside the layer scale
 * (UI_GUIDELINES §4.1), so they order themselves against sheets and modals by
 * accident rather than by design; and an `absolute` panel is clipped by any
 * ancestor with `overflow-hidden`, which is what made the import row's
 * suggestions unreachable (fixed once in IngredientTemplateCombobox and
 * then not carried across).
 *
 * A portal puts the panel outside those ancestors, and
 * `z-[var(--z-popover)]` puts it where the layer scale says popovers go. Radix
 * brings the parts the hand-rolled version left out: Escape, outside-click,
 * focus return to the trigger, and `aria-expanded` on the trigger itself.
 */
export function InlinePopover({
  open,
  onOpenChange,
  trigger,
  children,
  align = "end",
  className,
}: InlinePopoverProps) {
  return (
    <PopoverPrimitive.Root open={open} onOpenChange={onOpenChange}>
      <PopoverPrimitive.Trigger asChild>{trigger}</PopoverPrimitive.Trigger>
      <PopoverPrimitive.Portal>
        <PopoverPrimitive.Content
          align={align}
          sideOffset={4}
          className={cn(
            "z-[var(--z-popover)] rounded-xl border border-border bg-surface-card shadow-xl p-2",
            "animate-in fade-in zoom-in-95 duration-150",
            className,
          )}
        >
          {children}
        </PopoverPrimitive.Content>
      </PopoverPrimitive.Portal>
    </PopoverPrimitive.Root>
  );
}
