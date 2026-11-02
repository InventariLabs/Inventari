import { useTranslation } from "react-i18next";
import { ChefHat, Info } from "lucide-react";

import { InlineQueryError } from "@/components/ui/QueryResult";
import { PurposeBindingSelect } from "@/modules/settings/components/ai/PurposeBindingSelect";
import {
  useAiConnections,
  useAiPurposes,
} from "@/modules/settings/hooks/useAiConnections";

/** The registry keys of the two purposes recipes owns. Shared with the
 * import flow, which refuses to offer URL import while nothing is bound
 * to the reader. */
export const RECIPES_PURPOSE_KEY = "recipes.text_parse";
const RECIPES_URL_FETCH_PURPOSE_KEY = "recipes.url_fetch";

/**
 * Which AI connections parse a pasted recipe and read a page for the
 * URL import.
 *
 * Rendered in two places on purpose: on the global AI screen next to the other
 * purposes, and on the recipes module settings page next to the options it
 * belongs with. Both drive the same binding endpoint, so there is one value
 * per purpose — unlike the reader key, which used to live on this screen in
 * a field that asked a cook what a rate limit is.
 *
 * The connections themselves belong to the installation, not to this module,
 * so they come from the `settings` shared layer (AGENTS.md, Module-First File
 * Placement). Copying the select here to avoid the import would give the two
 * screens two implementations of one setting.
 */
export function RecipesAiSettings() {
  const { t } = useTranslation(["recipes", "common"]);
  const {
    data: connections = [],
    isError: connectionsFailed,
    error: connectionsError,
    refetch: refetchConnections,
  } = useAiConnections();
  const {
    data: purposes = [],
    isError: purposesFailed,
    error: purposesError,
    refetch: refetchPurposes,
  } = useAiPurposes();

  const recipesPurpose = purposes.find((p) => p.key === RECIPES_PURPOSE_KEY);
  const readerPurpose = purposes.find(
    (p) => p.key === RECIPES_URL_FETCH_PURPOSE_KEY,
  );

  return (
    <div>
      <div className="flex items-center gap-3 mb-6">
        <div className="w-9 h-9 bg-primary-50 text-on-secondary rounded-lg flex items-center justify-center">
          <ChefHat size={18} strokeWidth={2.5} />
        </div>
        <div>
          <h3 className="text-sm font-semibold text-on">
            {t("settings.aiSection.title")}
          </h3>
          <p className="text-xs font-medium text-on-muted uppercase tracking-wider mt-0.5">
            {t("settings.aiSection.subtitle")}
          </p>
        </div>
      </div>

      {connectionsFailed || purposesFailed ? (
        // Without the registry "bind it in the main settings" and an empty
        // connection list would both be wrong answers about what is set up.
        <InlineQueryError
          error={connectionsFailed ? connectionsError : purposesError}
          onRetry={() => {
            if (connectionsFailed) void refetchConnections();
            if (purposesFailed) void refetchPurposes();
          }}
        />
      ) : recipesPurpose ? (
        <PurposeBindingSelect
          purpose={recipesPurpose}
          connections={connections}
        />
      ) : (
        <p className="text-xs font-medium text-on-muted flex items-center gap-2 italic">
          <Info size={12} />
          {t("settings.aiSection.bindInMain")}
        </p>
      )}
      {readerPurpose && (
        <div className="mt-4">
          <PurposeBindingSelect
            purpose={readerPurpose}
            connections={connections}
          />
        </div>
      )}
    </div>
  );
}
