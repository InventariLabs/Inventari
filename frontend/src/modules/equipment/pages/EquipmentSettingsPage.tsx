import { useTranslation } from "react-i18next";
import { ModuleSettingsScreen } from "@/modules/shared/components/ModuleSettingsScreen";

/**
 * Equipment settings, inside the module they configure. The module exposes
 * warranty and maintenance warning windows, and had eight nav entries and no
 * way to reach any of them without leaving for the App Store.
 */
export default function EquipmentSettingsPage() {
  const { t } = useTranslation("equipment");
  return (
    <ModuleSettingsScreen
      moduleName="equipment"
      title={t("settings.module_title")}
      subtitle={t("settings.module_subtitle")}
    />
  );
}
