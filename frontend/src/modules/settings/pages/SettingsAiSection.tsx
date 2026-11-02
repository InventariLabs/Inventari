import { useEffect } from "react";
import { useTranslation } from "react-i18next";
import { useModulePageHeader } from "@/hooks/useModulePageHeader";
import SettingsAiTab from "../components/ai/AiConnectionsTab";

/**
 * AI connections, rendered at /settings/ai for whoever holds
 * `org:settings:write` — the key their writes ask for.
 *
 * Split out of the former "Developer" section, which held this and the
 * organization's mail server: two administrative subjects under a heading that
 * described neither, and the only route to either.
 */
export default function SettingsAiSection() {
  const { t } = useTranslation("common");
  const { setHeader } = useModulePageHeader();

  useEffect(() => {
    setHeader({ title: t("settings.tabs.ai") });
    return () => setHeader({});
  }, [t, setHeader]);

  return (
    <div className="space-y-6 pb-32 animate-in fade-in slide-in-from-bottom-2 duration-300">
      <SettingsAiTab />
    </div>
  );
}
