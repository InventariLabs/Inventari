import { useTranslation } from "react-i18next";
import type { LucideIcon } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { useCanWrite } from "@/hooks/useCanWrite";
import { EmptyState, type EmptyStateStep } from "@/components/ui/EmptyState";

export interface GettingStartedStep extends EmptyStateStep {
  /** Optional CTA label rendered after the step list (e.g. "Create your first asset"). */
  ctaLabel?: string;
  /** Optional CTA target — router path or callback. */
  ctaTo?: string;
  /** Optional callback when CTA is clicked. */
  onCta?: () => void;
}

export interface GettingStartedProps {
  /** Module namespace (e.g. "equipment"). Used to derive i18n keys. */
  moduleName: string;
  /** Lucide icon. */
  icon?: LucideIcon;
  /** Short description shown below the title. */
  description?: string;
  /** Ordered list of steps. */
  steps: GettingStartedStep[];
}

/**
 * Empty-state with numbered "getting started" steps.
 *
 * Convention: translate the title via `<moduleName>:gettingStarted.title`
 * and each step via `<moduleName>:gettingStarted.step<N>.title` /
 * `<moduleName>:gettingStarted.step<N>.description`.
 *
 * Example (equipment module):
 *   <GettingStarted
 *     moduleName="equipment"
 *     icon={Package}
 *     steps={[
 *       { title: t('equipment:gettingStarted.step1.title'),
 *         description: t('equipment:gettingStarted.step1.description') },
 *       ...
 *     ]}
 *   />
 */
export function GettingStarted({
  moduleName,
  icon,
  description,
  steps,
}: GettingStartedProps) {
  const { t } = useTranslation("common");
  // Every CTA here starts something — an import, a first record — so an
  // account that cannot write in the module is not offered one.
  const canWrite = useCanWrite(moduleName);
  const ctaSteps = canWrite ? steps.filter((step) => step.ctaLabel) : [];

  return (
    <EmptyState
      icon={icon}
      title={t(`${moduleName}:gettingStarted.title`, {
        defaultValue: "Get started",
      })}
      description={description ?? t(`${moduleName}:gettingStarted.description`)}
      variant="steps"
      steps={steps.map((step) => ({
        title: step.title,
        description: step.description,
      }))}
      primaryAction={
        ctaSteps.length > 0 ? (
          <div className="flex flex-wrap items-center justify-center gap-2">
            {ctaSteps.map((step, index) => {
              const testId = index === 0 ? "getting-started-cta" : undefined;
              // A callback has no address, and an <a> without href is neither
              // a link nor a tab stop: the keyboard skipped the only CTA.
              if (step.onCta) {
                return (
                  <Button
                    key={step.ctaLabel}
                    type="button"
                    variant={index === 0 ? "primary" : "outline"}
                    onClick={step.onCta}
                    data-testid={testId}
                  >
                    {step.ctaLabel}
                  </Button>
                );
              }
              return (
                <a
                  key={step.ctaLabel}
                  href={step.ctaTo}
                  data-testid={testId}
                  className={
                    index === 0
                      ? "inline-flex items-center justify-center h-10 px-4 rounded-lg bg-primary-700 dark:bg-primary-800 text-white text-sm font-medium hover:bg-primary-800 dark:hover:bg-primary-900"
                      : "inline-flex items-center justify-center h-10 px-4 rounded-lg border border-border text-sm font-medium text-on hover:bg-surface-muted"
                  }
                >
                  {step.ctaLabel}
                </a>
              );
            })}
          </div>
        ) : undefined
      }
    />
  );
}
