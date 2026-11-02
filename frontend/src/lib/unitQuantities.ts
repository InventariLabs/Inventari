/**
 * Lines grouped by the unit they are measured in.
 *
 * A progress bar or a summary that adds 20 pieces to 12.5 kilograms and 30
 * packs answers a question nobody asked, in no unit at all ("56.5/62.5").
 * Quantities may be added up only when they share a measure — a pack is not
 * a share of a piece — so a caller that shows a total groups its lines first
 * and renders one figure per unit.
 *
 * The unit is the line's symbol as the wire carries it; a line with no unit
 * recorded forms a group of its own rather than joining a symbol group. The
 * groups keep first-appearance order, so a card lists units the way its
 * lines do.
 */
export interface UnitGroup<T> {
  /** The unit symbol the group's lines share; null for unit-less lines. */
  unit: string | null;
  lines: T[];
}

export function groupLinesByUnit<T>(
  lines: readonly T[],
  unitOf: (line: T) => string | null | undefined,
): UnitGroup<T>[] {
  const groups = new Map<string | null, T[]>();
  for (const line of lines) {
    const key = unitOf(line)?.trim() || null;
    const group = groups.get(key);
    if (group) {
      group.push(line);
    } else {
      groups.set(key, [line]);
    }
  }
  return Array.from(groups, ([unit, groupLines]) => ({
    unit,
    lines: groupLines,
  }));
}
