import { useCallback, useMemo, useState } from "react";
import type { DocumentMetaData, SetMetaData } from "@/lib/moduleRegistry";
import { withModuleValues } from "@/modules/warehouse/components/documentFormShared";

/**
 * Other modules' fields on the document a screen is building — starting from
 * the saved *document*'s when one is edited — and the setter its form slot
 * hands them. Each module writes under its own name; the screen sends the
 * whole object with the document.
 */
export function useDocumentMetaData(document?: {
  meta_data?: DocumentMetaData | null;
}) {
  const [metaData, setAll] = useState<DocumentMetaData>(
    () => document?.meta_data ?? {},
  );

  const setMetaData = useCallback<SetMetaData>(
    (module, values) =>
      setAll((current) => withModuleValues(current, module, values)),
    [],
  );
  const resetMetaData = useCallback(() => setAll({}), []);

  return useMemo(
    () => ({ metaData, setMetaData, resetMetaData }),
    [metaData, setMetaData, resetMetaData],
  );
}
