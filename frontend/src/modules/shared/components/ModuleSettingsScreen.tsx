import { useEffect } from "react";
import { useTranslation } from "react-i18next";
import { Settings, ShieldAlert } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { EmptyState } from "@/components/ui/EmptyState";
import LoadingSpinner from "@/components/LoadingSpinner";
import { useModulePageHeader } from "@/hooks/useModulePageHeader";
import { apiErrorStatus } from "@/lib/errors";
import { ModuleSettingsForm } from "@/modules/settings/components/ModuleSettingsForm";
import { useModuleSettings } from "@/modules/settings/hooks/useModuleSettings";

interface ModuleSettingsScreenProps {
  /** Backend module name — the key its settings schema is registered under. */
  moduleName: string;
  title: string;
  subtitle?: string;
  /** Rendered under the schema form, for options the schema cannot express. */
  children?: React.ReactNode;
}

/**
 * A module's own settings screen, inside the module it configures.
 *
 * Per UI_GUIDELINES §2.14a the options that change a module's behaviour belong
 * to its nav bar, as the last entry — not only to the global settings shell,
 * which is reached from the App Store and leads back out to it.
 *
 * Reading them is an administrator's right, so this screen has to answer three
 * different questions — "you may not", "it did not load" and "there is nothing
 * to configure" — which it used to answer with one sentence about a failure.
 */
export function ModuleSettingsScreen({
  moduleName,
  title,
  subtitle,
  children,
}: ModuleSettingsScreenProps) {
  const { t } = useTranslation("common");
  const { setHeader } = useModulePageHeader();
  const { data, isLoading, isError, error, refetch, isFetching } =
    useModuleSettings(moduleName);

  useEffect(() => {
    setHeader({ title, subtitle });
  }, [title, subtitle, setHeader]);

  if (isLoading) return <LoadingSpinner />;

  if (isError) {
    if (apiErrorStatus(error) === 403) {
      return (
        <EmptyState
          icon={ShieldAlert}
          title={t("settings.moduleSettings.forbidden")}
          description={t("settings.moduleSettings.forbiddenHint")}
        />
      );
    }
    return (
      <EmptyState
        icon={Settings}
        title={t("settings.moduleSettings.loadFailed")}
        description={t("settings.moduleSettings.loadFailedHint")}
        primaryAction={
          <Button
            variant="outline"
            onClick={() => refetch()}
            disabled={isFetching}
          >
            {t("actions.retry")}
          </Button>
        }
      />
    );
  }

  if (!data?.settings_schema) {
    return (
      <EmptyState
        icon={Settings}
        title={t("settings.moduleSettings.noSchema")}
        description={t("settings.moduleSettings.noSchemaHint")}
      />
    );
  }

  return (
    <div className="space-y-6">
      <ModuleSettingsForm
        moduleName={moduleName}
        schema={data.settings_schema}
        initialValues={data.settings}
      />
      {children}
    </div>
  );
}
