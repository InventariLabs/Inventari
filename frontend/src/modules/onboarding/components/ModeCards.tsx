import { Check, Box } from "lucide-react";
import { useTranslation } from "react-i18next";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/Button";
import { DynamicIcon } from "@/components/ui/DynamicIcon";
import { useProfileLabels } from "@/modules/settings/hooks/useProfileLabels";
import type { ProductProfile } from "@/types";

// The card beside the profiles is not a profile: it stands for one module that
// is the whole app. The organization still gets a neutral profile underneath,
// which Settings -> My modules returns to when the mode is left.
export const CHOSEN_MODULE = "__chosen_module__";

interface ModeCardsProps {
  profiles: ProductProfile[];
  selected: string | null;
  onSelect: (id: string) => void;
}

/** The first onboarding choice: the product profiles and the one-module card. */
export function ModeCards({ profiles, selected, onSelect }: ModeCardsProps) {
  const { t } = useTranslation("onboarding");
  // The cards are the only content this decision rests on — they must not
  // be the one English thing on a translated first screen.
  const profileLabels = useProfileLabels();
  const isChosenModule = selected === CHOSEN_MODULE;
  return (
    <div className="grid gap-4 w-full max-w-2xl sm:grid-cols-2">
      {profiles.map((profile) => {
        const isSelected = selected === profile.id;
        const labels = profileLabels(profile);
        return (
          <Button
            key={profile.id}
            variant="ghost"
            size="row"
            onClick={() => onSelect(profile.id)}
            aria-pressed={isSelected}
            className={cn(
              "relative flex-col items-start gap-3 rounded-xl border bg-surface-card p-5 whitespace-normal shadow-sm transition-all hover:bg-surface-card hover:shadow-md",
              isSelected
                ? "border-primary-500 bg-primary-50/30"
                : "border-border hover:border-primary-500/40",
            )}
          >
            {/* Selected check */}
            {isSelected && (
              <span className="absolute top-3 right-3 flex h-5 w-5 items-center justify-center rounded-full bg-primary-600 text-white">
                <Check size={12} strokeWidth={3} />
              </span>
            )}

            {/* Icon */}
            <div
              className={cn(
                "flex h-10 w-10 items-center justify-center rounded-lg",
                isSelected
                  ? "bg-primary-100 dark:bg-primary-500/20"
                  : "bg-surface-raised",
              )}
            >
              <DynamicIcon
                name={profile.icon ?? "Box"}
                size={20}
                className={
                  isSelected ? "text-primary-600" : "text-on-secondary"
                }
              />
            </div>

            {/* Text */}
            <div>
              <p className="text-base font-semibold text-on tracking-tight">
                {labels.name}
              </p>
              <p className="mt-0.5 text-sm text-on-secondary leading-snug">
                {labels.description}
              </p>
            </div>
          </Button>
        );
      })}
      <Button
        variant="ghost"
        size="row"
        onClick={() => onSelect(CHOSEN_MODULE)}
        aria-pressed={isChosenModule}
        className={cn(
          "relative flex-col items-start gap-3 rounded-xl border bg-surface-card p-5 whitespace-normal shadow-sm transition-all hover:bg-surface-card hover:shadow-md",
          isChosenModule
            ? "border-primary-500 bg-primary-50/30"
            : "border-border hover:border-primary-500/40",
        )}
      >
        {isChosenModule && (
          <span className="absolute top-3 right-3 flex h-5 w-5 items-center justify-center rounded-full bg-primary-600 text-white">
            <Check size={12} strokeWidth={3} />
          </span>
        )}
        <div
          className={cn(
            "flex h-10 w-10 items-center justify-center rounded-lg",
            isChosenModule
              ? "bg-primary-100 dark:bg-primary-500/20"
              : "bg-surface-raised",
          )}
        >
          <Box
            size={20}
            className={
              isChosenModule ? "text-primary-600" : "text-on-secondary"
            }
          />
        </div>
        <div>
          <p className="text-base font-semibold text-on tracking-tight">
            {t("singleModuleName")}
          </p>
          <p className="mt-0.5 text-sm text-on-secondary leading-snug">
            {t("singleModuleDescription")}
          </p>
        </div>
      </Button>
    </div>
  );
}
