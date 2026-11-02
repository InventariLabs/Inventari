import { useEffect, useState } from "react";
import { DynamicIcon } from "@/components/ui/DynamicIcon";
import LoadingSpinner from "@/components/LoadingSpinner";
import { QueryFailure } from "@/components/ui/QueryResult";
import { useModuleLabels } from "@/hooks/useModuleLabels";
import { moduleRegistry } from "@/lib/moduleRegistry";
import { registerModules } from "@/lib/moduleRegistry/moduleLoaders";
import { cn } from "@/lib/utils";
import { useAvailableModules } from "@/modules/settings/hooks/useModules";

interface FocusModuleStepProps {
  selected: string | null;
  onSelect: (moduleName: string) => void;
}

/**
 * The second step of the one-module choice: which module is the whole app.
 *
 * Only modules whose manifest declares `standalone` are listed — the same
 * list Settings -> My modules offers. A fresh organization has nothing enabled
 * yet, so the registry is asked against the whole catalogue rather than the
 * enabled set; the backend plans what the choice switches on. The shell
 * registers only enabled modules, so this step registers the catalogue itself —
 * without it the registry is empty here and the list with it.
 */
export function FocusModuleStep({ selected, onSelect }: FocusModuleStepProps) {
  const moduleLabels = useModuleLabels();
  const {
    data: available,
    isLoading,
    isError,
    error,
    refetch,
  } = useAvailableModules();

  const [registered, setRegistered] = useState(false);
  useEffect(() => {
    if (!available) return;
    let cancelled = false;
    void registerModules(available.map((m) => m.name)).then(() => {
      if (!cancelled) setRegistered(true);
    });
    return () => {
      cancelled = true;
    };
  }, [available]);

  if (isError) {
    return <QueryFailure error={error} onRetry={() => void refetch()} />;
  }
  if (isLoading || !registered) return <LoadingSpinner />;

  // Read only once registration has landed — before it the registry is empty.
  const byName = new Map((available ?? []).map((m) => [m.name, m]));
  const rows = moduleRegistry
    .getStandaloneModules([...byName.keys()])
    .flatMap((mod) => {
      const info = byName.get(mod.name);
      return info ? [info] : [];
    });
  return (
    <div className="w-full max-w-2xl" role="radiogroup">
      <ul className="divide-y divide-border rounded-xl border border-border bg-surface-card">
        {rows.map((module) => {
          const isOn = selected === module.name;
          const labels = moduleLabels(module);
          return (
            <li key={module.name}>
              <label
                htmlFor={`onboarding-focus-${module.name}`}
                className="flex cursor-pointer items-start gap-3 p-4"
              >
                <input
                  type="radio"
                  id={`onboarding-focus-${module.name}`}
                  name="onboarding-focus-module"
                  className="mt-1 shrink-0"
                  checked={isOn}
                  onChange={() => onSelect(module.name)}
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
    </div>
  );
}
