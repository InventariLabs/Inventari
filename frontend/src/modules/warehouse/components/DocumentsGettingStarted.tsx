import { FileCheck } from "lucide-react";
import { useTranslation } from "react-i18next";
import { GettingStarted } from "@/components/ui/GettingStarted";

/** What the register shows before the first document exists. */
export function DocumentsGettingStarted({
  onCreateFirst,
  receiptCode,
}: {
  onCreateFirst: () => void;
  /** The organization's own label for a receipt (PZ, IN, …), the one its
   *  numbers use: the step must not name a code the reader never sees. */
  receiptCode: string;
}) {
  const { t } = useTranslation("warehouse");
  return (
    <GettingStarted
      moduleName="warehouse"
      icon={FileCheck}
      description={t("gettingStarted.description")}
      steps={[
        {
          title: t("gettingStarted.step1.title"),
          description: t("gettingStarted.step1.description", {
            code: receiptCode,
          }),
          ctaLabel: t("gettingStarted.step1.cta"),
          onCta: onCreateFirst,
        },
        {
          title: t("gettingStarted.step2.title"),
          description: t("gettingStarted.step2.description"),
        },
        {
          title: t("gettingStarted.step3.title"),
          description: t("gettingStarted.step3.description"),
        },
      ]}
    />
  );
}
