import { useEffect } from "react";
import { Link, useParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { Settings, ShieldAlert, SearchX } from "lucide-react";
import { useModulePageHeader } from "@/hooks/useModulePageHeader";
import { Card } from "@/components/ui/Card";
import { EmptyState } from "@/components/ui/EmptyState";
import { useModuleLabels } from "@/hooks/useModuleLabels";
import { useModuleSettings } from "@/modules/settings/hooks/useModuleSettings";
import { ModuleSettingsForm } from "@/modules/settings/components/ModuleSettingsForm";
import LoadingSpinner from "@/components/LoadingSpinner";
import { moduleRegistry } from "@/lib/moduleRegistry";
import { makeTDynamic } from "@/lib/i18nHelpers";
import { apiErrorStatus } from "@/lib/errors";

/**
 * The generic, schema-driven settings screen. Mounted at
 * `/settings/modules/:name` and, via a module manifest's `settingsSections`,
 * under the module's own static settings path — pass `moduleName` there,
 * because a static route carries no `:name` param.
 */
export default function ModuleSettingsPage({
  moduleName,
}: {
  moduleName?: string;
} = {}) {
  const params = useParams<{ name: string }>();
  const name = moduleName ?? params.name;
  const { t } = useTranslation("common");
  const { setHeader } = useModulePageHeader();
  const { data, isLoading, isError, error } = useModuleSettings(name);

  // the header shows the module's display name from the registry
  // (translated), not the raw module identifier.
  const moduleDef = name ? moduleRegistry.getModule(name) : undefined;
  const moduleLabel = useModuleLabels();
  const labels = name
    ? moduleLabel({ name, display_name: name, description: "" })
    : null;
  const displayName =
    labels?.name && labels.name !== name
      ? labels.name
      : moduleDef?.launcher
        ? makeTDynamic(t)(moduleDef.launcher.displayName)
        : name;
  const description = labels?.description === name ? "" : labels?.description;

  // The shell's header is the only one on this screen. It used to say "Module
  // settings: X" above a card that said "X" above the sentence "Module-level
  // configuration" — the same title twice, and the space meant for describing
  // this module spent on describing the page.
  useEffect(() => {
    if (!name) return;
    setHeader({
      title: displayName,
      subtitle: description || undefined,
      backTo: "/apps",
    });
    return () => setHeader({});
  }, [name, displayName, description, setHeader]);

  if (!name) {
    return (
      <EmptyState
        title={t("settings.moduleSettings.noName", "Missing module name")}
        description={t("settings.moduleSettings.noNameHint")}
      />
    );
  }

  if (isLoading) {
    return <LoadingSpinner />;
  }

  if (isError || !data) {
    // One sentence used to cover three different situations: no permission,
    // no such module, and a request that genuinely failed. They call for
    // three different next steps.
    const status = apiErrorStatus(error);
    const storeLink = (
      <Link
        to="/apps"
        className="inline-flex items-center justify-center h-10 px-4 rounded-lg bg-primary-700 dark:bg-primary-800 text-white text-sm font-medium hover:bg-primary-800 dark:hover:bg-primary-900"
      >
        {t("settings.modules.openAppStore", "Open Modules")}
      </Link>
    );

    if (status === 403) {
      return (
        <EmptyState
          icon={ShieldAlert}
          title={t("settings.moduleSettings.forbidden")}
          description={t("settings.moduleSettings.forbiddenHint")}
        />
      );
    }

    if (status === 404) {
      return (
        <EmptyState
          icon={SearchX}
          title={t("settings.moduleSettings.unknownModule")}
          description={t("settings.moduleSettings.unknownModuleHint")}
          primaryAction={storeLink}
        />
      );
    }

    return (
      <EmptyState
        icon={Settings}
        title={t(
          "settings.moduleSettings.loadFailed",
          "Could not load settings",
        )}
        description={t("settings.moduleSettings.loadFailedHint")}
        primaryAction={storeLink}
      />
    );
  }

  if (!data.settings_schema) {
    // The landing state for an enabled module this installation knows but
    // that exposes nothing to configure — a registered module whose schema
    // is empty, and an always-on feature (items, locations, categories)
    // whose settings live nowhere. Both must read as "no settings here",
    // not as an error and not as a module the installation lacks.
    return (
      <Card className="p-6">
        <div className="flex items-start gap-3">
          <Settings className="text-on-muted shrink-0 mt-0.5" size={20} />
          <div>
            <h2 className="text-base font-semibold text-on leading-tight">
              {t(
                "settings.moduleSettings.noSchema",
                "This module has no settings",
              )}
            </h2>
            <p className="text-sm text-on-muted mt-1">
              {t(
                "settings.moduleSettings.noSchemaHint",
                "There is nothing to configure on this screen. If the module offers options, you will find them in its own screens.",
              )}
            </p>
          </div>
        </div>
      </Card>
    );
  }

  // No card, no second heading, no bottom link back to where the header's
  // own back arrow already goes.
  return (
    <ModuleSettingsForm
      moduleName={name}
      schema={data.settings_schema}
      initialValues={data.settings}
    />
  );
}
