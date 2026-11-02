import { useCallback } from "react";
import { useTranslation } from "react-i18next";

import type { ProductProfile } from "@/types";

export interface ProfileLabels {
  name: string;
  description: string;
}

/**
 * Resolves the user-visible workspace-mode name and description.
 *
 * Single source of truth: `profiles.<id>.name` / `profiles.<id>.description`
 * in the `common` i18n namespace (see docs/MODULE_NAMES.md § "Workspace mode
 * names"). The registry's `name` / `description` are only a fallback for
 * profiles outside this distribution, which the frontend cannot know at build
 * time — the same contract `useModuleLabels` has with manifest `display_name`.
 *
 * Returns a resolver rather than the labels so it is safe to call per item
 * inside a list render without breaking the rules of hooks.
 */
export function useProfileLabels() {
  const { t } = useTranslation("common");
  return useCallback(
    (
      profile: Pick<ProductProfile, "id" | "name" | "description">,
    ): ProfileLabels => ({
      name: t(`profiles.${profile.id}.name`, { defaultValue: profile.name }),
      description: t(`profiles.${profile.id}.description`, {
        defaultValue: profile.description,
      }),
    }),
    [t],
  );
}
