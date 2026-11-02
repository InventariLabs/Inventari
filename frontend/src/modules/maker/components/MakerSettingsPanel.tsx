import { useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { ChevronDown } from "lucide-react";
import { toast } from "sonner";
import { Card } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { ReadOnlyNotice } from "@/components/ui/ReadOnlyNotice";
import { QueryFailure } from "@/components/ui/QueryResult";
import { useCanManage, useCanWrite } from "@/hooks/useCanWrite";
import {
  useMakerSettings,
  useUpdateMakerSettings,
} from "@/modules/maker/hooks/useRecipes";
import type {
  AvailabilityCheckScope,
  CreateOnShortageStrategy,
  ReferenceDirection,
  MakerSettingsUpdate,
} from "@/modules/maker/types/maker";
import { extractApiError } from "@/lib/errors";
import { cn } from "@/lib/utils";
import { resultTerms } from "@/modules/maker/hooks/useResultTerms";

/**
 * The policy switches, folded away. Each has a default that suits a small
 * workshop, and none of them has to be decided before the first order — yet
 * shown at the same weight as the result's name they read as a form to fill
 * in first.
 */
function AdvancedSection({ children }: { children: ReactNode }) {
  const { t } = useTranslation("maker");
  const [open, setOpen] = useState(false);
  return (
    <section className="space-y-4">
      <Button
        type="button"
        size="content"
        variant="ghost"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-controls="maker-settings-advanced"
        className="w-full justify-between rounded-lg px-1 py-2 text-left"
        data-testid="maker-settings-advanced-toggle"
      >
        <span className="min-w-0">
          <span className="block text-base font-semibold text-on">
            {t("settings.advanced")}
          </span>
          <span className="block text-xs font-normal text-on-secondary mt-0.5">
            {t("settings.advancedHint")}
          </span>
        </span>
        <ChevronDown
          size={18}
          aria-hidden="true"
          className={cn(
            "shrink-0 text-on-muted transition-transform",
            open && "rotate-180",
          )}
        />
      </Button>
      {open && (
        <div id="maker-settings-advanced" className="space-y-6">
          {children}
        </div>
      )}
    </section>
  );
}

export function MakerSettingsPanel() {
  const { t } = useTranslation("maker");
  // Module settings are configuration the organization lives by — a shortage
  // strategy decides what production does to stock — so they sit behind
  // maker:manage, not the floor's maker:write.
  const canManage = useCanManage("maker");
  const canWrite = useCanWrite("maker");
  const {
    data: settings,
    isLoading,
    isError,
    error,
    refetch,
  } = useMakerSettings();
  const updateMutation = useUpdateMakerSettings();

  const [direction, setDirection] = useState<ReferenceDirection>("MARGIN");
  const [allowOver, setAllowOver] = useState(true);
  const [scope, setScope] = useState<AvailabilityCheckScope>("GLOBAL");
  const [strategy, setStrategy] = useState<CreateOnShortageStrategy>("ALLOW");
  const [initialized, setInitialized] = useState(false);

  // Sync local state when settings load.
  if (settings && !initialized) {
    setDirection(settings.reference_direction);
    setAllowOver(settings.allow_overproduction);
    setScope(settings.availability_check_scope);
    setStrategy(settings.create_on_shortage_strategy);
    setInitialized(true);
  }

  // The neighbouring module already answers this the right way: an account
  // that cannot change how a module behaves is told so instead of being shown
  // switches. Here the panel drew all of them, promised that every choice
  // saves itself, and turned the 403 into "Failed to save settings" — a
  // sentence about a failure where the truth was a boundary. The notice names
  // the right the account lacks: left at its default it asked about
  // maker:write for everyone, which the floor holds, so it drew nothing at
  // all for the very account it exists to speak to.
  if (!canManage) {
    return (
      <ReadOnlyNotice module="maker" right={canWrite ? "manage" : "write"} />
    );
  }

  // `!settings` used to stand in for "still loading". After a failed read
  // `isLoading` is already false and `settings` stays undefined, so the
  // loading card was shown for ever — no message, no way out.
  if (isError) {
    return (
      <Card className="p-8">
        <QueryFailure error={error} onRetry={() => refetch()} />
      </Card>
    );
  }

  if (isLoading || !settings) {
    return (
      <Card className="p-8 text-center text-on-muted text-sm">
        {t("settings.loading")}
      </Card>
    );
  }

  function handleSave(changes: MakerSettingsUpdate, resetState?: () => void) {
    updateMutation.mutate(changes, {
      onSuccess: () => {
        toast.success(t("settings.saved", { defaultValue: "Settings saved" }));
      },
      onError: (err) => {
        toast.error(
          extractApiError(
            err,
            t("settings.saveFailed", {
              defaultValue: "Failed to save settings",
            }),
          ),
        );
        resetState?.();
      },
    });
  }

  return (
    // No heading of its own: the module page header already names this screen,
    // and two "Maker settings" titles stacked is one title too many.
    <div className="space-y-6">
      <p className="text-xs text-on-muted">{t("settings.immediateNote")}</p>

      {/* Reference direction */}
      <Card className="p-4">
        <h3 className="text-sm font-semibold text-on mb-1">
          {t("settings.referenceDirection")}
        </h3>
        <p className="text-xs text-on-muted mb-1">
          {t("settings.referenceDirectionHint")}
        </p>
        <p className="text-xs text-on-secondary mb-3">
          {t("settings.whereReferenceDirection")}
        </p>
        <div className="flex flex-wrap gap-2">
          <Button
            type="button"
            variant={direction === "SAVINGS" ? "success" : "outline"}
            onClick={() => {
              const old = direction;
              setDirection("SAVINGS");
              handleSave({ reference_direction: "SAVINGS" }, () =>
                setDirection(old),
              );
            }}
            disabled={updateMutation.isPending}
            data-testid="maker-settings-savings-btn"
          >
            {resultTerms(t, "SAVINGS").label}
          </Button>
          <Button
            type="button"
            variant={direction === "MARGIN" ? "success" : "outline"}
            onClick={() => {
              const old = direction;
              setDirection("MARGIN");
              handleSave({ reference_direction: "MARGIN" }, () =>
                setDirection(old),
              );
            }}
            disabled={updateMutation.isPending}
            data-testid="maker-settings-margin-btn"
          >
            {resultTerms(t, "MARGIN").label}
          </Button>
        </div>
        <p
          className="text-xs text-on-secondary mt-2"
          data-testid="maker-settings-result-definition"
        >
          {resultTerms(t, direction).definition}
        </p>
      </Card>

      <AdvancedSection>
        {/* Allow overproduction */}
        <Card className="p-4">
          <div className="flex items-start justify-between gap-4">
            <div>
              <h3 className="text-sm font-semibold text-on mb-1">
                {t("settings.allowOverproduction")}
              </h3>
              <p className="text-xs text-on-muted">
                {t("settings.allowOverproductionHint")}
              </p>
            </div>
            {/* Toggle switch — custom UI element, not a standard button. Its
              transparent 2px border is the inset the knob travels within, not a
              visible frame, so the 1px rule of UI_GUIDELINES §2.10 skips it. */}
            {/* eslint-disable-next-line no-restricted-syntax */}
            <button
              type="button"
              role="switch"
              aria-checked={allowOver}
              // The heading beside it is visual context, not a name: without
              // this the rotor read a bare "switch" between bare neighbours.
              // The generic settings form names its checkbox the same way.
              aria-label={t("settings.allowOverproduction")}
              disabled={updateMutation.isPending}
              onClick={() => {
                const old = allowOver;
                const newVal = !allowOver;
                setAllowOver(newVal);
                handleSave({ allow_overproduction: newVal }, () =>
                  setAllowOver(old),
                );
              }}
              className={`relative inline-flex h-6 w-11 shrink-0 rounded-full border-2 border-transparent transition-colors disabled:cursor-not-allowed disabled:opacity-60 ${
                allowOver ? "bg-accent-600" : "bg-surface-hover-dark"
              }`}
              data-testid="maker-settings-overproduction-toggle"
            >
              <span
                className={`pointer-events-none inline-block h-5 w-5 transform rounded-full bg-white shadow ring-0 transition ${
                  allowOver ? "translate-x-5" : "translate-x-0"
                }`}
              />
            </button>
          </div>
        </Card>

        {/* Availability check scope */}
        <Card className="p-4">
          <h3 className="text-sm font-semibold text-on mb-1">
            {t("settings.availabilityCheckScope")}
          </h3>
          <p className="text-xs text-on-muted mb-3">
            {t("settings.availabilityCheckScopeHint")}
          </p>
          <div className="flex gap-2">
            <Button
              type="button"
              variant={scope === "GLOBAL" ? "success" : "outline"}
              onClick={() => {
                const old = scope;
                setScope("GLOBAL");
                handleSave({ availability_check_scope: "GLOBAL" }, () =>
                  setScope(old),
                );
              }}
              disabled={updateMutation.isPending}
              data-testid="maker-settings-scope-global"
            >
              {t("settings.scopeGlobal")}
            </Button>
            <Button
              type="button"
              variant={scope === "PER_LOCATION" ? "success" : "outline"}
              onClick={() => {
                const old = scope;
                setScope("PER_LOCATION");
                handleSave({ availability_check_scope: "PER_LOCATION" }, () =>
                  setScope(old),
                );
              }}
              disabled={updateMutation.isPending}
              data-testid="maker-settings-scope-per-location"
            >
              {t("settings.scopePerLocation")}
            </Button>
          </div>
        </Card>

        {/* Shortage strategy */}
        <Card className="p-4">
          <h3 className="text-sm font-semibold text-on mb-1">
            {t("settings.createOnShortageStrategy")}
          </h3>
          <p className="text-xs text-on-muted mb-3">
            {t("settings.createOnShortageStrategyHint")}
          </p>
          <div className="flex gap-2">
            {(["ALLOW", "WARN", "BLOCK"] as CreateOnShortageStrategy[]).map(
              (s) => (
                <Button
                  key={s}
                  type="button"
                  variant={strategy === s ? "success" : "outline"}
                  onClick={() => {
                    const old = strategy;
                    setStrategy(s);
                    handleSave({ create_on_shortage_strategy: s }, () =>
                      setStrategy(old),
                    );
                  }}
                  disabled={updateMutation.isPending}
                  data-testid={`maker-settings-strategy-${s.toLowerCase()}`}
                >
                  {t(
                    `settings.strategy${s.charAt(0)}${s.slice(1).toLowerCase()}`,
                  )}
                </Button>
              ),
            )}
          </div>
        </Card>
      </AdvancedSection>
    </div>
  );
}
