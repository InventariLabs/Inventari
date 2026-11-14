import { useEffect } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import { useModulePageHeader } from "@/module-sdk";

export default function IndexPage() {
  const { t } = useTranslation("mcp_server");
  const { setHeader } = useModulePageHeader();

  useEffect(() => {
    setHeader({ title: t("title"), subtitle: t("description") });
  }, [t, setHeader]);

  return (
    <div className="space-y-6">
      <p className="max-w-2xl text-sm text-muted-foreground">
        {t("description")}
      </p>
      <Link
        to="/settings/modules/mcp_server"
        className="text-sm font-medium text-primary-700 hover:underline"
      >
        {t("settings.open")}
      </Link>
    </div>
  );
}
