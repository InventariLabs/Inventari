import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useSearchParams } from "react-router-dom";
import { Loader2, Search, ShieldAlert } from "lucide-react";
import {
  useAvailableModules,
  useModuleEnablePreview,
  useToggleModule,
} from "@/modules/settings/hooks/useModules";
import { useModuleLabels } from "@/hooks/useModuleLabels";
import { useModules } from "@/contexts/ModulesContext";
import { useHasPermission } from "@/hooks/useHasPermission";
import { PageContainer } from "@/components/ui/PageContainer";
import { PageHeader } from "@/components/ui/PageHeader";
import { Input } from "@/components/ui/Input";
import { EmptyState } from "@/components/ui/EmptyState";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { QueryFailure } from "@/components/ui/QueryResult";
import ModuleStoreCard from "@/modules/settings/components/ModuleStoreCard";
import { ModuleStoreFilters } from "@/modules/settings/components/ModuleStoreFilters";
import { TypedSlot } from "@/components/Slot";
import { toast } from "sonner";
import { extractApiError } from "@/lib/errors";
import type { ModuleCategory, ModuleInfo } from "@/types";

type FilterCategory = "all" | "active" | "available" | ModuleCategory;

/** Every taxonomy bucket, in the order the sidebar offers them. */
const CATEGORY_ORDER: ModuleCategory[] = [
  "core",
  "business",
  "analytics",
  "integrations",
  "system",
  "other",
];

const EMPTY_SLOT_DATA = {};

/**
 * Modules whose "off" reaches outside the workspace, and the sentence that says
 * how.
 *
 * Switching one of these off revokes something that is live right now: every
 * key issued here stops authenticating, every endpoint stops being sent to. The
 * toast afterwards is too late to be a warning, and an admin reaching for this
 * lever because they suspect a leaked key deserves to be told it is the right
 * lever — the sentence works both ways.
 *
 * Every other module asks too, with the general sentence about its data
 * (``offConsequencesGeneral``): screens disappear, data stays, switching back
 * undoes it. An admin tidying the store could not tell a module they never
 * used from one with production history inside — the toggle alone said
 * nothing either way — so the map below is an upgrade of the sentence, not
 * the question's gate.
 */
const OFF_HAS_CONSEQUENCES: Record<string, string> = {
  api_keys: "appStore.offConsequencesApiKeys",
  webhooks: "appStore.offConsequencesWebhooks",
};

/**
 * The sentence for a module whose switch-on would put saved things into
 * motion, said before it happens (the module answers how many through
 * `GET /modules/{name}/enable-preview`). Webhooks is the one that answers: its
 * saved addresses start receiving as soon as it is on, which the person who
 * switched it off may no longer remember — and the person switching it on may
 * never have known.
 */
const ON_RESUMES: Record<string, string> = {
  webhooks: "appStore.onResumesWebhooks",
  // Any other module that answers with a number and has no sentence of its own.
  general: "appStore.onResumesGeneral",
};

const CATEGORY_LABEL_KEY: Record<ModuleCategory, string> = {
  core: "appStore.categoryCore",
  business: "appStore.categoryBusiness",
  analytics: "appStore.categoryAnalytics",
  integrations: "appStore.categoryIntegrations",
  system: "appStore.categorySystem",
  other: "appStore.categoryOther",
};

/**
 * AppStore — module marketplace page at /apps.
 * Admin-only: lists all available modules with activate/deactivate controls.
 */
export default function AppStore() {
  const { t } = useTranslation(["common", "modules"]);
  const { isModuleEnabled, refreshModules, hiddenModules = [] } = useModules();
  const {
    data: allAvailableModules = [],
    isLoading,
    isError,
    error,
    refetch,
  } = useAvailableModules();
  const availableModules = allAvailableModules.filter(
    (module) => !hiddenModules.includes(module.name),
  );
  const toggleMutation = useToggleModule();
  const enablePreview = useModuleEnablePreview();
  const moduleLabel = useModuleLabels();

  const isAdmin = useHasPermission("admin:access");

  // A refusal is an answer, not a bounce. The store used to
  // `navigate("/")`, so a manager who followed a link to it landed on the
  // launcher with nothing said and no idea why.

  const [filter, setFilter] = useState<FilterCategory>("all");
  const [search, setSearch] = useState("");

  // `?module=partners` — a screen elsewhere sent the reader here to switch one
  // module on. Landing them on sixteen tiles and letting them hunt is how the
  // name got lost between the two screens, so the search opens on it.
  const [searchParams] = useSearchParams();
  const requestedModule = searchParams.get("module");
  const searchSeeded = useRef(false);
  useEffect(() => {
    if (!requestedModule || searchSeeded.current) return;
    if (availableModules.length === 0) return;
    searchSeeded.current = true;
    const found = availableModules.find((mod) => mod.name === requestedModule);
    setSearch(found ? moduleLabel(found).name : requestedModule);
  }, [requestedModule, availableModules, moduleLabel]);

  // The module whose deactivation is waiting on an answer, if any.
  const [pendingOff, setPendingOff] = useState<{
    name: string;
    displayName: string;
    warningKey: string;
  } | null>(null);

  // The module whose activation is waiting on an answer, with how many saved
  // things would start acting.
  const [pendingOn, setPendingOn] = useState<{
    name: string;
    displayName: string;
    resumes: number;
  } | null>(null);

  const pendingOnTitle = pendingOn
    ? t(`modules.${pendingOn.name}.name`, {
        ns: "modules",
        defaultValue: pendingOn.displayName || pendingOn.name,
      })
    : null;

  const pendingOffTitle = pendingOff
    ? t(`modules.${pendingOff.name}.name`, {
        ns: "modules",
        defaultValue: pendingOff.displayName || pendingOff.name,
      })
    : null;

  const handleToggle = async (
    moduleName: string,
    currentlyEnabled: boolean,
    displayName: string,
  ) => {
    // Every switch-off asks first; the map above only upgrades the sentence
    // for the modules whose off reaches outside the workspace.
    if (currentlyEnabled) {
      setPendingOff({
        name: moduleName,
        displayName,
        warningKey:
          OFF_HAS_CONSEQUENCES[moduleName] ?? "appStore.offConsequencesGeneral",
      });
      return;
    }
    // Switching on asks only when something saved would start acting. The
    // answer is advice: a read that fails must not leave the module unable to
    // be switched on, so it falls through to the plain switch, which reports
    // its own refusal.
    const { resumes } = await enablePreview
      .mutateAsync(moduleName)
      .catch(() => ({ resumes: 0 }));
    if (resumes > 0) {
      setPendingOn({ name: moduleName, displayName, resumes });
      return;
    }
    await applyToggle(moduleName, currentlyEnabled, displayName);
  };

  const applyToggle = async (
    moduleName: string,
    currentlyEnabled: boolean,
    displayName: string,
  ) => {
    try {
      await toggleMutation.mutateAsync({
        moduleName,
        enabled: !currentlyEnabled,
      });
      await refreshModules();
      // fall back to the human display name (not the raw module id)
      // when the i18n key is missing.
      const moduleTitle = t(`modules.${moduleName}.name`, {
        ns: "modules",
        defaultValue: displayName || moduleName,
      });
      if (!currentlyEnabled) {
        toast.success(t("modules:success.enabled", { name: moduleTitle }));
      } else {
        toast.success(t("modules:success.disabled", { name: moduleTitle }));
      }
    } catch (error) {
      // The server explains itself here — "Module 'printing' is always enabled
      // and cannot be turned off" — and the empty catch replaced that with a
      // generic sentence, so the reader kept clicking a button that could
      // never work.
      toast.error(extractApiError(error, t("modules:errors.updateFailed")));
    }
  };

  // Only categories with something in them. A filter that can only ever
  // answer "No modules found" — the same sentence a failed search gets — is
  // worse than no filter: it reads as "not installed".
  const presentCategories = new Set(
    availableModules.map((mod) => mod.category ?? "other"),
  );

  // Requirements and soft companions are named on the card, so they need their own entry here:
  // the translated name and the display-name fallback both live on ModuleInfo.
  const modulesByName = new Map(availableModules.map((mod) => [mod.name, mod]));

  /** Which of *names* are modules in the store that are not switched on here. */
  const notSwitchedOn = (names: string[] | undefined): ModuleInfo[] =>
    (names ?? [])
      .map((name) => modulesByName.get(name))
      .filter(
        (other): other is ModuleInfo =>
          other !== undefined &&
          !isModuleEnabled(other.name) &&
          other.is_always_on !== true,
      );

  // Named as each module's own card names it. Built outside the hint's t()
  // call on purpose: a nested t() with its own namespace inside the options
  // object makes check-i18n-keys read the outer key as the inner namespace's.
  const moduleNames = (mods: ModuleInfo[]): string =>
    mods
      .map((other) =>
        t(`modules.${other.name}.name`, {
          ns: "modules",
          defaultValue: other.display_name,
        }),
      )
      .join(", ");

  const filterCategories: { id: FilterCategory; label: string }[] = [
    { id: "all", label: t("appStore.filterAll") },
    { id: "active", label: t("appStore.filterActive") },
    { id: "available", label: t("appStore.filterAvailable") },
    ...CATEGORY_ORDER.filter((category) => presentCategories.has(category)).map(
      (category) => ({
        id: category as FilterCategory,
        label: t(CATEGORY_LABEL_KEY[category]),
      }),
    ),
  ];

  const filteredModules = availableModules.filter((mod) => {
    const isEnabled = isModuleEnabled(mod.name);

    // Text search: the translated label/description come first — that is what
    // the user sees on the tile. The technical name and the manifest originals
    // stay in the haystack on purpose: someone who knows `maker` must still
    // find it.
    if (search.trim()) {
      const needle = search.toLowerCase();
      const label = moduleLabel(mod);
      const haystack =
        `${label.name} ${label.description} ${mod.display_name} ${mod.description} ${mod.name}`.toLowerCase();
      if (!haystack.includes(needle)) return false;
    }

    // Category/status filter
    switch (filter) {
      case "active":
        return isEnabled;
      case "available":
        return !isEnabled;
      case "all":
        return true;
      default:
        return (mod.category ?? "other") === filter;
    }
  });

  if (!isAdmin) {
    return (
      <PageContainer>
        <EmptyState
          icon={ShieldAlert}
          title={t("settings.access.denied")}
          description={t("settings.access.deniedHint")}
        />
      </PageContainer>
    );
  }

  if (isLoading) {
    return (
      <PageContainer>
        <div className="flex justify-center py-24">
          <Loader2 className="animate-spin text-on-muted" size={32} />
        </div>
      </PageContainer>
    );
  }

  // The subtitle counts what arrived against what exists, so an empty answer
  // renders as "0 of the 0 modules offered here are switched on" — the same
  // sentence shape that says "11 of the 15" when the catalogue is there, and
  // therefore read as a fact about the installation. The count is withheld
  // along with the grid it counts.
  if (isError) {
    return (
      <PageContainer wide className="space-y-6">
        <PageHeader title={t("appStore.title")} backTo="/" />
        <QueryFailure error={error} onRetry={() => refetch()} />
      </PageContainer>
    );
  }

  return (
    <PageContainer wide className="space-y-6">
      {/* The shared header, not a hand-rolled one: the back arrow it draws
          pops history first and falls back to `backTo`, and it is hidden on a
          phone where the shell bar already carries one. */}
      <PageHeader
        title={t("appStore.title")}
        subtitle={t("appStore.subtitle", {
          total: availableModules.length,
          active: availableModules.filter((m) => isModuleEnabled(m.name))
            .length,
        })}
        backTo="/"
      />

      <div className="flex flex-col lg:flex-row gap-6">
        {/* Filters: a sidebar on a wide screen, a row of chips on a phone */}
        <aside className="lg:w-48 shrink-0">
          <ModuleStoreFilters
            filters={filterCategories}
            value={filter}
            onChange={setFilter}
            label={t("appStore.filterNav")}
          />
        </aside>

        {/* Main content */}
        <div className="flex-1 min-w-0 space-y-4">
          {/* Search */}
          <Input
            aria-label={t("appStore.searchPlaceholder")}
            placeholder={t("appStore.searchPlaceholder")}
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            leftIcon={<Search size={16} className="text-on-muted" />}
          />

          {/* Module grid */}
          {filteredModules.length === 0 ? (
            <EmptyState
              icon={Search}
              title={t("appStore.noResults")}
              variant="compact"
            />
          ) : (
            <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-3">
              {filteredModules.map((mod) => {
                const isEnabled = isModuleEnabled(mod.name);
                const missingRequirements = moduleNames(
                  notSwitchedOn(mod.requires),
                );
                return (
                  <ModuleStoreCard
                    key={mod.name}
                    module={mod}
                    isEnabled={isEnabled}
                    isBusy={
                      toggleMutation.isPending &&
                      toggleMutation.variables?.moduleName === mod.name
                    }
                    missingRequirementNames={missingRequirements}
                    missingCompanionNames={moduleNames(
                      notSwitchedOn(mod.optional_requires),
                    )}
                    onToggle={() =>
                      // The card already says what is missing; the press
                      // repeats it rather than asking the server to refuse.
                      !isEnabled && missingRequirements
                        ? toast.error(
                            t("appStore.requiresHint", {
                              names: missingRequirements,
                            }),
                          )
                        : handleToggle(mod.name, isEnabled, mod.display_name)
                    }
                  />
                );
              })}
            </div>
          )}

          {/* Cards contributed through `settings_module_card`. The slot used to
              hang on /settings/modules, a page whose whole content was a
              button pointing here. */}
          <TypedSlot name="settings_module_card" data={EMPTY_SLOT_DATA} />
        </div>
      </div>

      {pendingOn && pendingOnTitle && (
        <ConfirmDialog
          open
          variant="warning"
          title={t("appStore.activateConfirmTitle", { name: pendingOnTitle })}
          message={t(
            ON_RESUMES[
              pendingOn.name in ON_RESUMES ? pendingOn.name : "general"
            ],
            { count: pendingOn.resumes },
          )}
          confirmLabel={t("appStore.activateConfirm")}
          errorFallback={t("modules:errors.updateFailed")}
          onConfirm={async () => {
            const target = pendingOn;
            setPendingOn(null);
            await applyToggle(target.name, false, target.displayName);
          }}
          onCancel={() => setPendingOn(null)}
        />
      )}

      {pendingOff && pendingOffTitle && (
        <ConfirmDialog
          open
          variant="danger"
          title={t("appStore.deactivateConfirmTitle", {
            name: pendingOffTitle,
          })}
          message={t(pendingOff.warningKey)}
          confirmLabel={t("appStore.deactivate")}
          errorFallback={t("modules:errors.updateFailed")}
          onConfirm={async () => {
            const target = pendingOff;
            setPendingOff(null);
            await applyToggle(target.name, true, target.displayName);
          }}
          onCancel={() => setPendingOff(null)}
        />
      )}
    </PageContainer>
  );
}
