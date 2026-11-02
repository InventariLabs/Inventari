import { X } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/Button";

interface DocumentFormHeaderProps {
  isEdit: boolean;
  docType: string;
  onClose: () => void;
}

export function DocumentFormHeader({
  isEdit,
  docType,
  onClose,
}: DocumentFormHeaderProps) {
  const { t } = useTranslation("warehouse");

  return (
    <div className="flex items-center justify-between p-4 sm:p-5 border-b border-border flex-shrink-0">
      <div>
        <h2 className="font-semibold text-on">
          {isEdit ? t("form.editTitle") : t("form.createTitle")}
        </h2>
        <p className="text-xs text-on-secondary mt-0.5 hidden sm:block">
          {t(
            `picker.${{ IN: "receiveSubtitle", OUT: "dispatchSubtitle", INT: "transferSubtitle", INTERNAL_IN: "internalReceiptSubtitle", INTERNAL_OUT: "internalIssueSubtitle", CORRECTION: "correctionSubtitle", SCRAP: "scrapSubtitle" }[docType] ?? "receiveSubtitle"}` as string,
          )}
        </p>
      </div>
      <Button
        variant="ghost"
        size="icon"
        onClick={onClose}
        aria-label={t("common:actions.close")}
      >
        <X size={18} />
      </Button>
    </div>
  );
}
