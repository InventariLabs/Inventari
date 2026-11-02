import { Link } from "react-router-dom";
import { DynamicIcon } from "@/components/ui/DynamicIcon";
import { cn } from "@/lib/utils";

/**
 * The colour a segment is drawn in. `ok` is the neutral mass — the part of a
 * row with nothing to report — and is most of the bar on most days; the
 * others are the anomalies a reader scans the bars for.
 */
export type CompositionTone =
  "ok" | "active" | "warning" | "danger" | "info" | "success";

export const COMPOSITION_TONE_CLASS: Record<CompositionTone, string> = {
  ok: "bg-bar-ok",
  active: "bg-bar-active",
  warning: "bg-amber-400",
  danger: "bg-red-500",
  info: "bg-blue-400",
  success: "bg-success-500",
};

/** The narrowest a non-empty segment is ever drawn, in pixels. */
export const SEGMENT_MIN_PX = 4;

interface SegmentCount {
  key: string;
  count: number;
}

export interface CompositionSegment extends SegmentCount {
  tone: CompositionTone;
}

interface SegmentGeometry {
  key: string;
  /** Flex grow factor: the segment's share of the fill is grow / Σgrow. */
  grow: number;
  minWidthPx: number;
}

export interface CompositionBarGeometry {
  /** The fill's length as a percentage of the track. */
  fillPercent: number;
  /**
   * The fill never gets narrower than the minimums of the segments inside
   * it. Without this, a row of 7 on a scale of 412 drew about ten pixels of
   * fill and three four-pixel segments spilling past it.
   */
  fillMinWidthPx: number;
  segments: SegmentGeometry[];
}

/**
 * Where the bar's pieces go. Pure, so the proportions and the clamp are
 * tested without a layout engine.
 *
 * Length is linear in the row's count against the largest row on the card,
 * so two bars compare at a glance. Inside the fill, each segment grows in
 * proportion to its count and is held at `SEGMENT_MIN_PX` at least — flexbox
 * takes the difference from the segments that can spare it, which in practice
 * is the neutral mass.
 */
export function compositionBarGeometry(
  count: number,
  maxCount: number,
  segments: readonly SegmentCount[],
): CompositionBarGeometry {
  // `!(x > 0)` rather than `x <= 0`: a count that did not arrive (NaN,
  // undefined) is no fill, not a NaN-wide one.
  if (!(count > 0) || !(maxCount > 0)) {
    return { fillPercent: 0, fillMinWidthPx: 0, segments: [] };
  }
  const present = segments.filter((s) => s.count > 0);
  return {
    fillPercent: (Math.min(count, maxCount) / maxCount) * 100,
    fillMinWidthPx: present.length * SEGMENT_MIN_PX,
    segments: present.map((s) => ({
      key: s.key,
      grow: s.count,
      minWidthPx: SEGMENT_MIN_PX,
    })),
  };
}

interface CompositionBarProps {
  count: number;
  /** The largest count among the rows this bar is compared with. */
  maxCount: number;
  segments: readonly CompositionSegment[];
  /**
   * A sentence with the numbers ("58 items: 4 expiring, 1 expired"). Colour
   * is never the only carrier of what the bar says.
   */
  ariaLabel: string;
  className?: string;
}

/**
 * A horizontal bar whose length is a row's size and whose colours are what
 * that row is made of. Presentation only — the caller counts.
 */
export function CompositionBar({
  count,
  maxCount,
  segments,
  ariaLabel,
  className,
}: CompositionBarProps) {
  const geometry = compositionBarGeometry(count, maxCount, segments);
  const toneOf = new Map(segments.map((s) => [s.key, s.tone]));
  return (
    <div
      role="img"
      aria-label={ariaLabel}
      className={cn(
        "flex h-1.5 w-full overflow-hidden rounded-full bg-surface-inset",
        className,
      )}
    >
      {geometry.segments.length > 0 && (
        <div
          data-fill=""
          className="flex h-full overflow-hidden rounded-full"
          style={{
            width: `${geometry.fillPercent}%`,
            minWidth: `${geometry.fillMinWidthPx}px`,
          }}
        >
          {geometry.segments.map((s) => (
            <span
              key={s.key}
              data-segment={s.key}
              className={cn(
                "h-full",
                COMPOSITION_TONE_CLASS[toneOf.get(s.key) ?? "ok"],
              )}
              style={{
                flexGrow: s.grow,
                flexShrink: 1,
                flexBasis: 0,
                minWidth: `${s.minWidthPx}px`,
              }}
            />
          ))}
        </div>
      )}
    </div>
  );
}

interface LegendEntry {
  key: string;
  tone: CompositionTone;
  label: string;
}

interface CompositionLegendProps {
  entries: readonly LegendEntry[];
  /** The segments of every bar the legend explains. */
  bars: readonly (readonly SegmentCount[])[];
  /** Names the list for assistive technology ("Legend"). */
  ariaLabel?: string;
  className?: string;
}

/**
 * The key to a card of composition bars. It names only the colours that
 * appear on the card: a legend promising "expired" in red above bars with
 * no red in them sends the reader looking for something that is not there.
 */
export function CompositionLegend({
  entries,
  bars,
  ariaLabel,
  className,
}: CompositionLegendProps) {
  const present = new Set(
    bars.flatMap((segs) => segs.filter((s) => s.count > 0).map((s) => s.key)),
  );
  const shown = entries.filter((e) => present.has(e.key));
  if (shown.length === 0) return null;
  return (
    <ul
      aria-label={ariaLabel}
      className={cn(
        "flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-on-muted",
        className,
      )}
    >
      {shown.map((e) => (
        <li key={e.key} className="flex items-center gap-1.5">
          <span
            aria-hidden="true"
            className={cn(
              "h-2 w-2 shrink-0 rounded-full",
              COMPOSITION_TONE_CLASS[e.tone],
            )}
          />
          {e.label}
        </li>
      ))}
    </ul>
  );
}

interface CompositionRowProps {
  /** A Lucide icon name, drawn in the row's tile. */
  icon: string;
  name: string;
  /** Where the name leads, when the row stands for something with a page. */
  href?: string;
  /** The row's own numbers in words: "3 locations · 1 expiring". */
  meta?: string;
  count: number;
  maxCount: number;
  segments: readonly CompositionSegment[];
  ariaLabel: string;
}

/**
 * One row of a composition card: icon, name, bar, count. Below `sm` the bar
 * takes a line of its own under the name; above it, the bar sits between the
 * name and the count. An empty row keeps its track, so a zero reads as a
 * zero and not as a gap in the card.
 */
export function CompositionRow({
  icon,
  name,
  href,
  meta,
  count,
  maxCount,
  segments,
  ariaLabel,
}: CompositionRowProps) {
  return (
    <li className="flex flex-wrap items-center gap-x-3 gap-y-2 py-2.5">
      <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-surface-raised text-on-secondary">
        <DynamicIcon name={icon} size={16} />
      </span>
      <div className="min-w-0 flex-1 sm:w-48 sm:flex-none">
        {href ? (
          <Link
            to={href}
            className="block truncate text-sm font-semibold text-on hover:underline py-3 md:py-1"
          >
            {name}
          </Link>
        ) : (
          <p className="truncate text-sm font-semibold text-on">{name}</p>
        )}
        {meta && <p className="text-xs text-on-muted">{meta}</p>}
      </div>
      <div className="order-last basis-full sm:order-none sm:basis-0 sm:flex-1">
        {count > 0 ? (
          <CompositionBar
            count={count}
            maxCount={maxCount}
            segments={segments}
            ariaLabel={ariaLabel}
          />
        ) : (
          <div
            aria-hidden="true"
            className="h-1.5 w-full rounded-full bg-surface-inset"
          />
        )}
      </div>
      <span className="min-w-8 shrink-0 text-right text-sm tabular-nums text-on">
        {count}
      </span>
    </li>
  );
}
