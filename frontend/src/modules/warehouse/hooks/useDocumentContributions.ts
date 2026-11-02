import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import type { ListControlBarSecondaryFilter } from "@/components/ui/ListControlBar";
import { useEnabledModulesOptional } from "@/contexts/ModulesContext";
import { moduleRegistry } from "@/lib/moduleRegistry";
import type {
  DocumentActionContributor,
  DocumentColumnContributor,
  DocumentFilterContributor,
  DocumentMetaData,
  DocumentView,
} from "@/lib/moduleRegistry";
import type {
  WarehouseDocument,
  WarehouseDocumentRow,
} from "@/modules/warehouse/types";

/** A contribution, beside the module that made it. */
export type FromModule<T> = T & { moduleName: string };

export interface DocumentContributions {
  columns: FromModule<DocumentColumnContributor>[];
  filters: FromModule<DocumentFilterContributor>[];
  actions: FromModule<DocumentActionContributor>[];
}

/**
 * What the named modules add to the documents, each tagged with the module it
 * came from — which a filter needs to name itself to the server. Read here,
 * from the modules' declarations, rather than by the registry: the documents
 * are this module's, and the registry ships on every screen's first paint.
 */
function documentContributions(
  enabledModules: string[],
): DocumentContributions {
  const contributions: DocumentContributions = {
    columns: [],
    filters: [],
    actions: [],
  };
  for (const moduleName of enabledModules) {
    const module = moduleRegistry.getModule(moduleName);
    if (!module) continue;
    for (const c of module.documentColumnContributors ?? [])
      contributions.columns.push({ ...c, moduleName });
    for (const c of module.documentFilterContributors ?? [])
      contributions.filters.push({ ...c, moduleName });
    for (const c of module.documentActionContributors ?? [])
      contributions.actions.push({ ...c, moduleName });
  }
  return contributions;
}

/**
 * What enabled modules add to the documents: the list's columns and filter
 * chips and the document page's actions. Recomputed only when the set of
 * enabled modules changes, so the arrays keep their identity between renders.
 */
export function useDocumentContributions(): DocumentContributions {
  const enabledModules = useEnabledModulesOptional();
  return useMemo(() => documentContributions(enabledModules), [enabledModules]);
}

/**
 * The module filters a documents list has on, each `<module>:<name>`; the
 * list sends them to the server, which narrows by them.
 */
export function useModuleFilters() {
  const [active, setActive] = useState<string[]>([]);
  return {
    active,
    toggle: (name: string) =>
      setActive((names) =>
        names.includes(name)
          ? names.filter((n) => n !== name)
          : [...names, name],
      ),
    clear: () => setActive([]),
  };
}

/**
 * What enabled modules add to one page of a documents list: the columns
 * some document on it fills, and the filters, each with whether it is on.
 * Both lists — History and Documents — read it, so a module's contribution
 * reaches every list of documents.
 */
export function useDocumentListContributions(
  documents: WarehouseDocumentRow[],
  moduleFilters: ReturnType<typeof useModuleFilters>,
): {
  columns: FromModule<DocumentColumnContributor>[];
  filters: ListControlBarSecondaryFilter[];
} {
  const { t } = useTranslation();
  const contributions = useDocumentContributions();
  const columns = useMemo(
    () =>
      contributions.columns.filter(
        (column) =>
          !column.hasValue ||
          documents.some((doc) => column.hasValue!(toDocumentView(doc))),
      ),
    [contributions.columns, documents],
  );
  const filters = contributions.filters.map((filter) => {
    const name = `${filter.moduleName}:${filter.key}`;
    return {
      key: name,
      label: t(filter.label),
      active: moduleFilters.active.includes(name),
      onToggle: () => moduleFilters.toggle(name),
    };
  });
  return { columns, filters };
}

function metaData(value: unknown): DocumentMetaData {
  return (value ?? {}) as DocumentMetaData;
}

/**
 * The document as a module's contribution reads it (`DocumentView`).
 *
 * A row of a documents list carries only the lines a module can read
 * something on — those with a module's fields (`module_lines`); the
 * document's own screen carries all of them.
 */
export function toDocumentView(
  doc: WarehouseDocument | WarehouseDocumentRow,
): DocumentView {
  const lines = "module_lines" in doc ? doc.module_lines : (doc.lines ?? []);
  return {
    id: doc.id,
    type: doc.type,
    number: doc.number,
    status: doc.status,
    metaData: metaData(doc.meta_data),
    lines: lines.map((line) => ({
      id: line.id,
      batchNumber: line.batch_number ?? null,
      metaData: metaData(line.meta_data),
    })),
  };
}
