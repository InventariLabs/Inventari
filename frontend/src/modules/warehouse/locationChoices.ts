import type { StorageLocationSummary } from "@/types";
import { LOCATION_PATH_SEPARATOR } from "@/utils/helpers";

/** What a screen needs to know of a place Core named by id. */
export interface LocationChoice {
  id: string;
  path: string;
  /** The location's own name, without its ancestors — what the floor card
   *  prints under the code. */
  name?: string;
  /** The places above it, joined — the caption under its name in a picker.
   *  Absent for a place at the top of its chain. */
  parentPath?: string;
  /** The code printed on the location's label, when it has one. */
  code?: string | null;
  /** Whether nothing stands below it: a shelf rather than a zone. */
  leaf?: boolean;
}

/**
 * A place Core named by id, as the choice a screen looks things up in: its
 * code, whether anything stands below it, and the way to it.
 */
export function locationChoiceOf(
  summary: Pick<
    StorageLocationSummary,
    "id" | "name" | "full_path" | "short_code" | "is_leaf"
  >,
): LocationChoice {
  const chain = summary.full_path
    ? summary.full_path.split(LOCATION_PATH_SEPARATOR)
    : [summary.name];
  return {
    id: summary.id,
    path: chain.join(LOCATION_PATH_SEPARATOR),
    name: summary.name,
    parentPath:
      chain.length > 1
        ? chain.slice(0, -1).join(LOCATION_PATH_SEPARATOR)
        : undefined,
    code: summary.short_code ?? null,
    leaf: summary.is_leaf,
  };
}

/** Which of a line's own places a shelf is, when it is one of them. */
export type LineChoiceMark = "current" | "planned";
