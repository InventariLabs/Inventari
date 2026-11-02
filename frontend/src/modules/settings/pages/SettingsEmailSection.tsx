import { useEffect } from "react";
import { useTranslation } from "react-i18next";
import { useModulePageHeader } from "@/hooks/useModulePageHeader";
import FailedEmailsCard from "../components/FailedEmailsCard";
import SettingsEmailTab from "../components/SettingsEmailTab";

/**
 * Mail server settings — admin only, rendered at /settings/email.
 *
 * Configuring SMTP is an administrative act, not a programming one, and it is
 * what makes invitations and notifications leave the building. It used to sit
 * under "Developer", where an administrator looking for it had no reason to go.
 */
export default function SettingsEmailSection() {
  const { t } = useTranslation("common");
  const { setHeader } = useModulePageHeader();

  useEffect(() => {
    setHeader({ title: t("settings.tabs.email") });
    return () => setHeader({});
  }, [t, setHeader]);

  return (
    <div className="space-y-6 pb-32 animate-in fade-in slide-in-from-bottom-2 duration-300">
      <SettingsEmailTab />
      <FailedEmailsCard />
    </div>
  );
}
