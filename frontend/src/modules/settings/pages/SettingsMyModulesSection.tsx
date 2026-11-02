import { useEffect } from "react";
import { useTranslation } from "react-i18next";
import { useModulePageHeader } from "@/hooks/useModulePageHeader";
import { WorkspaceModeSettings } from "../components/WorkspaceModeSettings";
import { FocusModeSettings } from "../components/FocusModeSettings";

/**
 * "My modules" settings section rendered at /settings/my-modules (admin-only).
 *
 * The one place that decides which modules the workspace shows: the module set
 * a profile switches on, and the "show only <module>" toggles. The launcher's
 * profile chip and the module switcher both lead here, so there is one door to
 * open when the question is "which modules do I see".
 */
export default function SettingsMyModulesSection() {
  const { t } = useTranslation("common");
  const { setHeader } = useModulePageHeader();

  useEffect(() => {
    setHeader({
      title: t("settings.tabs.myModules"),
      subtitle: t("settings.myModules.subtitle"),
    });
  }, [t, setHeader]);

  return (
    <div className="space-y-6 pb-32 animate-in fade-in slide-in-from-bottom-2 duration-300">
      <WorkspaceModeSettings />
      <FocusModeSettings />
    </div>
  );
}
