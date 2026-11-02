import { useMemo } from "react";
import { useQueries } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { moduleRegistry } from "@/lib/moduleRegistry";
import type { ListFilterContributor } from "@/lib/moduleRegistry";

export interface ModuleListFilterChip {
  key: string;
  label: string;
  active: boolean;
  onToggle: () => void;
}

/**
 * Filter chips that modules contribute to a Core list.
 *
 * Core cannot filter by a module's own attribute — "has a formula" is maker's
 * question — so each contributor answers it as a set of product template ids
 * and Core narrows to them through its neutral `template_ids` filter. The
 * table is virtualised, so the answer has to arrive for the whole catalogue
 * rather than row by row.
 *
 * `useQueries` rather than a hook per contributor: enabling or disabling a
 * module changes how many there are, and a variable number of hook calls is
 * exactly what the rules of hooks forbid.
 *
 * Known ceiling: the ids travel in the query string, ~37 bytes each, against
 * nginx's default 8 KB request line — roughly 200 templates. Past that the
 * request fails visibly (414) rather than quietly returning the wrong rows;
 * a catalogue that large needs the filter to move to a POST search body.
 */
/**
 * The answers alone, one per contributor. `useQueries` shares a `combine`
 * result structurally, so this array keeps its identity until an answer
 * changes — and "still loading" (`undefined`) and "nothing matches" (`[]`)
 * are different answers, where a joined string had made them one.
 * Module-level, because a new function each render re-runs the combine.
 */
function pickData(
  results: { data: string[] | undefined }[],
): (string[] | undefined)[] {
  return results.map((r) => r.data);
}

export function useModuleListFilters(
  table: string,
  enabledModules: string[],
  active: string[],
  onToggle: (key: string) => void,
): { chips: ModuleListFilterChip[]; templateIds: string[] | undefined } {
  const { t } = useTranslation();

  const contributors: ListFilterContributor[] = useMemo(
    () => moduleRegistry.getListFilterContributors(table, enabledModules),
    [table, enabledModules],
  );

  const idSets = useQueries({
    queries: contributors.map((contributor) => ({
      queryKey: contributor.queryKey,
      queryFn: () => contributor.fetchTemplateIds(),
      // Only fetch the ids a chip actually needs — an inactive chip costs
      // nothing, and the label does not depend on them.
      enabled: active.includes(contributor.key),
      staleTime: 60_000,
    })),
    combine: pickData,
  });

  const chips = contributors.map((contributor) => ({
    key: contributor.key,
    label: t(contributor.label),
    active: active.includes(contributor.key),
    onToggle: () => onToggle(contributor.key),
  }));

  // Intersection: two active chips mean "both", not "either". `undefined`
  // while a needed set is still loading, so the list is left alone rather
  // than emptied — an id list of `[]` would match nothing.
  const templateIds = useMemo(() => {
    const loaded = contributors
      .map((contributor, index) =>
        active.includes(contributor.key) ? idSets[index] : null,
      )
      .filter((ids) => ids !== null);
    if (loaded.length === 0) return undefined;
    if (loaded.some((ids) => ids === undefined)) return undefined;
    return (loaded as string[][]).reduce((acc, ids) =>
      acc.filter((id) => ids.includes(id)),
    );
  }, [contributors, active, idSets]);

  return { chips, templateIds };
}
