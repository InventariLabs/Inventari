import * as React from "react";
import { cn } from "@/lib/utils";

export interface ScrollRowProps extends React.HTMLAttributes<HTMLDivElement> {
  /** Classes for the scrolling track (layout of the row itself). */
  className?: string;
}

/**
 * A horizontally scrollable row that says so.
 *
 * A bare `overflow-x-auto` hides its overflow with a hard edge: on a 390px
 * screen the status filters ended at "Confirmed" and nothing suggested that
 * "Completed" and "Cancelled" existed. The browser's own answer — a thick grey
 * scrollbar under the row — reads as a UI element rather than as an affordance.
 *
 * So: the scrollbar is hidden and the content fades out at whichever end still
 * has content behind it. The fade is a mask on the content, not a gradient
 * overlay, so the row works on any background.
 *
 * The children stay focusable, so a keyboard reaches the off-screen items by
 * tabbing; the container deliberately does not add a tab stop of its own.
 *
 * The track carries `px-1 -mx-1 py-1 -my-1`: once `overflow-x` is not
 * `visible`, both axes clip, and a track with no padding is exactly as tall as
 * its tallest child and starts exactly where its first child starts — so
 * anything a child draws outside its border-box (a `ring-*` box-shadow, a
 * focus `outline`, a border) loses the pixels on that side. The vertical half
 * of this was fixed first; the horizontal half was not, and the first chip in
 * every filter row had its left edge shaved off against the clip. The padding
 * gives that paint room on all four sides; the negative margin keeps the
 * surrounding layout unchanged.
 */
export function ScrollRow({ className, children, ...rest }: ScrollRowProps) {
  const trackRef = React.useRef<HTMLDivElement>(null);
  const [edges, setEdges] = React.useState({ start: false, end: false });

  const measure = React.useCallback(() => {
    const el = trackRef.current;
    if (!el) return;
    // 1px slack: fractional widths make scrollLeft land just short of the end.
    const start = el.scrollLeft > 1;
    const end = el.scrollLeft + el.clientWidth < el.scrollWidth - 1;
    setEdges((prev) =>
      prev.start === start && prev.end === end ? prev : { start, end },
    );
  }, []);

  React.useEffect(() => {
    const el = trackRef.current;
    if (!el) return;
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(el);
    for (const child of Array.from(el.children)) observer.observe(child);
    return () => observer.disconnect();
  }, [measure, children]);

  const mask =
    edges.start || edges.end
      ? `linear-gradient(to right, ${
          edges.start ? "transparent 0, #000 1.5rem" : "#000 0"
        }, ${edges.end ? "#000 calc(100% - 1.5rem), transparent 100%" : "#000 100%"})`
      : undefined;

  return (
    <div
      ref={trackRef}
      onScroll={measure}
      style={mask ? { maskImage: mask, WebkitMaskImage: mask } : undefined}
      className={cn(
        "overflow-x-auto px-1 -mx-1 py-1 -my-1 [-ms-overflow-style:none] [scrollbar-width:none] [&::-webkit-scrollbar]:hidden",
        className,
      )}
      {...rest}
    >
      {children}
    </div>
  );
}
