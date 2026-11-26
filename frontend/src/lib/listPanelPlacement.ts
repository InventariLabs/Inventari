/** Where a fixed suggestion panel stands against the input it belongs to. */
export interface ListPanelPlace {
  left: number;
  width: number;
  maxHeight: number;
  /** Set when the panel opens downward: its top edge sits under the input. */
  top?: number;
  /** Set when it opens upward: its bottom edge sits on the input's top. */
  bottom?: number;
}

/**
 * Places a suggestion panel below its input, or above it when the room below
 * is short. Upward, the panel is anchored by its bottom edge to the input's top
 * rather than placed from a guess of its height: a list taller than the guess
 * grows away from the input instead of running down over it.
 *
 * `visibleHeight` is what the person can see (an on-screen keyboard shrinks
 * it); `layoutHeight` is the viewport a `position: fixed` box is measured
 * against, which the keyboard leaves as it was.
 */
export function placeListPanel(
  rect: Pick<DOMRect, "top" | "bottom" | "left" | "width">,
  estimatedHeight: number,
  visibleHeight: number,
  layoutHeight: number,
): ListPanelPlace {
  const gap = 4;
  const spaceBelow = visibleHeight - rect.bottom - gap;
  const up = spaceBelow < estimatedHeight && rect.top > spaceBelow;
  const base = { left: rect.left, width: rect.width };
  return up
    ? {
        ...base,
        bottom: layoutHeight - rect.top + gap,
        maxHeight: Math.max(96, rect.top - 16),
      }
    : {
        ...base,
        top: rect.bottom + gap,
        maxHeight: Math.min(240, spaceBelow),
      };
}
