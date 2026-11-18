import { useEffect } from "react";
import { useTranslation } from "react-i18next";
import { useModulePageHeader } from "@/hooks/useModulePageHeader";
import { MakerSettingsPanel } from "@/modules/maker/components/MakerSettingsPanel";

/**
 * Maker settings, inside the module they configure.
 *
 * The options sit beside the screens they change. They are not integrations,
 * so they do not belong in the "Integrations" group of the global /settings
 * shell.
 */
export default function MakerSettingsPage() {
  const { t } = useTranslation("maker");
  const { setHeader } = useModulePageHeader();

  useEffect(() => {
    setHeader({
      title: t("settings.title"),
      subtitle: t("settings.subtitle"),
    });
  }, [t, setHeader]);

  return (
    <div className="space-y-6">
      <MakerSettingsPanel />
    </div>
  );
}
