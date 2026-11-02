import { useEffect } from "react";
import { useTranslation } from "react-i18next";

import { useModulePageHeader } from "@/hooks/useModulePageHeader";
import { POApprovalSettings } from "../components/POApprovalSettings";

export default function POSettingsPage() {
  const { t } = useTranslation("purchase_orders");
  const { setHeader } = useModulePageHeader();

  useEffect(() => {
    setHeader({
      backTo: "/purchase-orders",
      title: t("settings.pageTitle"),
      subtitle: t("settings.pageSubtitle"),
    });
  }, [t, setHeader]);

  // the settings card was capped at 670px and centred while the header
  // stayed left-aligned, leaving a lone card floating in an empty page. Fill
  // the width like the other module screens.
  return (
    <div className="space-y-6">
      <POApprovalSettings />
    </div>
  );
}
