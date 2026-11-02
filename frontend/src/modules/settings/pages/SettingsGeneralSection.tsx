import { useEffect } from "react";
import { useTranslation } from "react-i18next";
import { useLocation } from "react-router-dom";
import { useModulePageHeader } from "@/hooks/useModulePageHeader";
import ModuleDataVisibilitySettings from "../components/ModuleDataVisibilitySettings";
import OrganizationSettings from "../components/OrganizationSettings";
import PermanentDeleteSettings from "../components/PermanentDeleteSettings";
import SettingsDataTab from "../components/SettingsDataTab";

/**
 * General settings section rendered at /settings (index).
 * Combines organization profile management with app-level data settings.
 * The module set (product profile) switch lives in its own admin-only
 * section at /settings/my-modules.
 */
export default function SettingsGeneralSection() {
  const { t } = useTranslation("common");
  const { setHeader } = useModulePageHeader();
  const { hash } = useLocation();

  // The screens that keep module-owned data out of their lists deep-link
  // here: "/settings#module-data" must land on the switch, not on the top of
  // a page where it sits below the fold.
  useEffect(() => {
    if (hash !== "#module-data") return;
    document
      .getElementById("module-data")
      ?.scrollIntoView({ behavior: "smooth", block: "center" });
  }, [hash]);

  useEffect(() => {
    setHeader({
      title: t("settings.tabs.general"),
      subtitle: t("settings.subtitle"),
    });
  }, [t, setHeader]);

  return (
    <div className="space-y-6 pb-32 animate-in fade-in slide-in-from-bottom-2 duration-300">
      <OrganizationSettings />
      <ModuleDataVisibilitySettings />
      <PermanentDeleteSettings />
      <SettingsDataTab />
    </div>
  );
}
