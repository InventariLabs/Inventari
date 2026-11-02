import { useEffect } from "react";
import { useTranslation } from "react-i18next";
import { useModulePageHeader } from "@/hooks/useModulePageHeader";
import { MakerSettingsPanel } from "@/modules/maker/components/MakerSettingsPanel";

/**
 * Maker settings, inside the module they configure.
 *
 * They used to live only under the global /settings shell, in its
 * "Integrations" group between API keys and webhooks — neither an
 * integration nor anywhere near the screens the options change.
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
