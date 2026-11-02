import { useTranslation } from "react-i18next";
import { SettingsSectionHeader } from "./SettingsSectionHeader";
import { ModuleSettingsForm } from "@/modules/settings/components/ModuleSettingsForm";
import { useModuleSettings } from "@/modules/settings/hooks/useModuleSettings";
import { useHasPermission } from "@/hooks/useHasPermission";

/**
 * The module's own options — what the settings schema declares, today the
 * over-receipt tolerance — as the first section of the Settings screen.
 *
 * Reading them is an administrator's right, and the rest of the screen is
 * not: for anyone else the section is simply absent, and the query is never
 * sent, rather than answered with a refusal nobody asked to see. A schema
 * that is missing or fails to load leaves the profile below it usable, so
 * those states render nothing as well.
 */
export function ReceivingSettingsSection() {
  const { t } = useTranslation("warehouse");
  const isAdmin = useHasPermission("admin:access");
  const { data } = useModuleSettings(isAdmin ? "warehouse" : undefined);

  if (!isAdmin || !data?.settings_schema) return null;

  return (
    <section>
      <SettingsSectionHeader
        title={t("settings.receivingTitle")}
        hint={t("settings.receivingHint")}
      />
      <ModuleSettingsForm
        moduleName="warehouse"
        schema={data.settings_schema}
        initialValues={data.settings}
      />
    </section>
  );
}
