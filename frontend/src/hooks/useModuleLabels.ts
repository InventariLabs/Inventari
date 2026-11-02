import { useCallback } from "react";
import { useTranslation } from "react-i18next";

import type { ModuleInfo } from "@/types";

export interface ModuleLabels {
  name: string;
  description: string;
}

/**
 * Resolves the user-visible module name and description.
 *
 * Single source of truth: `modules.<name>.name` / `modules.<name>.description`
 * in the `modules` i18n namespace (see docs/MODULE_NAMES.md). The manifest's
 * `display_name` / `description` are only a fallback for community modules the
 * frontend does not know at build time.
 *
 * Returns a resolver rather than the labels so it is safe to call per item
 * inside a list render without breaking the rules of hooks.
 *
 * Lives in the core, not in the settings module: naming a module is not a
 * settings concern — the 404 screen, the webhook form and the onboarding
 * wizard all need it, and core files may not import from modules.
 */
export function useModuleLabels() {
  const { t } = useTranslation("modules");
  return useCallback(
    (
      mod: Pick<ModuleInfo, "name" | "display_name" | "description">,
    ): ModuleLabels => ({
      name: t(`modules.${mod.name}.name`, { defaultValue: mod.display_name }),
      description: t(`modules.${mod.name}.description`, {
        defaultValue: mod.description,
      }),
    }),
    [t],
  );
}
