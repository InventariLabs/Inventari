import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";

/**
 * The scroller around the week grid, with a fade on the trailing edge that
 * shows only while there is more grid behind it.
 *
 * The fade used to be drawn unconditionally. At a width where all seven days
 * fit there is nothing to hint at, and the 32px gradient sat over the last
 * column anyway, so its cards looked cut off at the right edge.
 */
export function MealPlanScroller({ children }: { children: ReactNode }) {
  const trackRef = useRef<HTMLDivElement>(null);
  const [more, setMore] = useState(false);

  const measure = useCallback(() => {
    const el = trackRef.current;
    if (!el) return;
    // 1px slack: fractional widths leave scrollLeft just short of the end.
    setMore(el.scrollLeft + el.clientWidth < el.scrollWidth - 1);
  }, []);

  useEffect(() => {
    const el = trackRef.current;
    if (!el) return;
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(el);
    for (const child of Array.from(el.children)) observer.observe(child);
    return () => observer.disconnect();
  }, [measure]);

  return (
    <div className="relative">
      {more && (
        <div
          className="pointer-events-none absolute inset-y-0 right-0 w-8 z-10 bg-gradient-to-l from-surface to-transparent"
          aria-hidden="true"
        />
      )}
      <div ref={trackRef} onScroll={measure} className="overflow-x-auto">
        {children}
      </div>
    </div>
  );
}
