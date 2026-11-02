import { useTranslation } from "react-i18next";

import { Checkbox } from "@/components/ui/Checkbox";
import { DynamicIcon } from "@/components/ui/DynamicIcon";
import LoadingSpinner from "@/components/LoadingSpinner";
import { QueryFailure } from "@/components/ui/QueryResult";
import { useModuleLabels } from "@/hooks/useModuleLabels";
import { cn } from "@/lib/utils";
import { useAvailableModules } from "@/modules/settings/hooks/useModules";
import type { ProductProfile } from "@/types";

interface ModuleChoiceStepProps {
  profile: ProductProfile;
  selected: string[];
  onToggle: (moduleName: string) => void;
}

/**
 * The second onboarding step: what the chosen mode starts with.
 *
 * A profile is a starting point, not a verdict. Three modules — production,
 * API keys and webhooks — belong to no profile, so before this step the
 * first move of the people who need them was "go into Settings and turn it
 * on yourself".
 *
 * Rows are the mode's own modules followed by what it offers, and only the
 * ones a reader can actually decide about. The always-on seven are left out
 * deliberately: a checkbox that cannot be unticked is a row that asks for a
 * decision it will not accept.
 */
export function ModuleChoiceStep({
  profile,
  selected,
  onToggle,
}: ModuleChoiceStepProps) {
  const { t } = useTranslation("onboarding");
  // The rows are the only content this decision rests on — they must not
  // be the one English thing on a translated first screen, the way the
  // profile cards once were.
  const moduleLabels = useModuleLabels();
  const {
    data: available,
    isLoading,
    isError,
    error,
    refetch,
  } = useAvailableModules();

  if (isLoading) return <LoadingSpinner />;
  // No rows would read as "this mode has nothing to choose" and skip the step.
  if (isError) {
    return <QueryFailure error={error} onRetry={() => void refetch()} />;
  }

  const byName = new Map((available ?? []).map((m) => [m.name, m]));
  const names = [
    ...profile.default_modules,
    ...(profile.suggested_modules ?? []),
  ];
  const rows = [...new Set(names)].flatMap((name) => {
    const module = byName.get(name);
    return module && !module.is_always_on ? [module] : [];
  });

  if (rows.length === 0) return null;

  return (
    <div className="w-full max-w-2xl">
      <ul className="divide-y divide-border rounded-xl border border-border bg-surface-card">
        {rows.map((module) => {
          const isOn = selected.includes(module.name);
          const labels = moduleLabels(module);
          return (
            <li key={module.name}>
              <label
                htmlFor={`onboarding-module-${module.name}`}
                className="flex cursor-pointer items-start gap-3 p-4"
              >
                <Checkbox
                  id={`onboarding-module-${module.name}`}
                  className="mt-0.5 shrink-0"
                  checked={isOn}
                  onChange={() => onToggle(module.name)}
                />
                <DynamicIcon
                  name={module.icon || "Box"}
                  size={18}
                  className={cn(
                    "mt-0.5 shrink-0",
                    isOn ? "text-primary-600" : "text-on-muted",
                  )}
                />
                <span className="min-w-0">
                  <span className="block text-sm font-medium text-on">
                    {labels.name}
                  </span>
                  <span className="mt-0.5 block text-sm text-on-secondary leading-snug">
                    {labels.description}
                  </span>
                </span>
              </label>
            </li>
          );
        })}
      </ul>
      <p className="mt-3 text-xs text-on-muted">{t("moduleChoiceFooter")}</p>
    </div>
  );
}
