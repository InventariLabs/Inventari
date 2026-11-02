import { useCallback, useMemo } from "react";
import { useTranslation } from "react-i18next";
import { moduleRegistry } from "@/lib/moduleRegistry";
import { useEnabledModulesOptional } from "@/contexts/ModulesContext";

/**
 * Names the purpose a label was generated for.
 *
 * The pool stores the purpose as a bare `context_tag` — the Core has no
 * opinion on what "equipment" means, and should not. The name comes from
 * whichever module claimed the tag; an unclaimed tag (its module was
 * uninstalled) falls back to the raw value rather than disappearing, because
 * a printed sheet of those labels is still on somebody's shelf.
 */
export function useLabelPurposeName(): (contextTag?: string | null) => string {
  const { t } = useTranslation(["labels"]);
  const enabledModules = useEnabledModulesOptional();

  const byTag = useMemo(() => {
    const map = new Map<string, string>();
    moduleRegistry
      .getLabelPurposes(enabledModules)
      .forEach((purpose) => map.set(purpose.contextTag, purpose.labelKey));
    return map;
  }, [enabledModules]);

  return useCallback(
    (contextTag?: string | null) => {
      if (!contextTag) return t("labels:generateModal.purposeProduct");
      const labelKey = byTag.get(contextTag);
      return labelKey ? t(labelKey, contextTag) : contextTag;
    },
    [byTag, t],
  );
}
