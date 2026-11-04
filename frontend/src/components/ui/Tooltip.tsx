import { cn } from "@/lib/utils";

/**
 * The words behind an icon-only control, shown on hover and on keyboard focus.
 *
 * Sits inside the control, which carries `relative group/tooltip` beside its
 * own classes: the bubble is positioned against the control and revealed by
 * its hover and its keyboard focus. The group is named rather than plain — a
 * list row is a `group` too, and an unnamed `group-hover` would open every
 * tooltip on the row the moment the pointer crossed any part of it.
 *
 * `title` is the usual spelling of this tooltip and is not carried beside it:
 * it answers hover only, never focus, and kept alongside this one it opens a
 * second bubble over the first. The words live here and in the control's
 * `aria-label` — the same words (UI_GUIDELINES §11.4).
 *
 * Hover opens it only where the pointer really hovers. A touch screen leaves
 * the last tapped control "hovered" until something else is tapped, which left
 * the words of a control standing over its row after the sheet it opened had
 * closed. The keyboard still opens it (`:focus-visible`, not plain focus: a sheet
 * returning focus to its trigger after a tap is not a keyboard user).
 *
 * A tooltip is not a control — nothing focuses it and nothing taps it — so it
 * carries `pointer-events-none` (UI_GUIDELINES §2.13c).
 */
export function Tooltip({
  label,
  side = "top",
}: {
  /** The words shown — the control's accessible name says the same. */
  label: string;
  /**
   * `left` for a control pressed against a surface that clips above it — the
   * phone card's swipe layer is `overflow-hidden`.
   */
  side?: "top" | "left";
}) {
  return (
    <span
      role="tooltip"
      className={cn(
        "pointer-events-none absolute z-20 whitespace-nowrap rounded-md bg-gray-900 px-2 py-1 text-[10px] font-medium text-white opacity-0 shadow-md transition-opacity [@media(hover:hover)]:group-hover/tooltip:opacity-100 group-has-[:focus-visible]/tooltip:opacity-100",
        side === "top"
          ? "bottom-full right-0 mb-1.5"
          : "right-full top-1/2 mr-1.5 -translate-y-1/2",
      )}
    >
      {label}
    </span>
  );
}
