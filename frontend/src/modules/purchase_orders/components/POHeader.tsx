import { useTranslation } from "react-i18next";
import { X } from "lucide-react";
import { Button } from "@/components/ui/Button";

interface POHeaderProps {
  isEdit: boolean;
  onClose: () => void;
  titleCreate: string;
  titleEdit: string;
  subtitleCreate: string;
  subtitleEdit: string;
  titleId?: string;
}

export function POHeader({
  isEdit,
  onClose,
  titleCreate,
  titleEdit,
  subtitleCreate,
  subtitleEdit,
  titleId,
}: POHeaderProps) {
  const { t } = useTranslation("common");

  return (
    <div className="flex items-center justify-between p-4 sm:p-5 border-b border-border flex-shrink-0">
      <div>
        <h2 id={titleId} className="font-semibold text-on text-lg">
          {isEdit ? titleEdit : titleCreate}
        </h2>
        <p className="text-xs text-on-muted mt-0.5 hidden sm:block">
          {isEdit ? subtitleEdit : subtitleCreate}
        </p>
      </div>
      <Button
        variant="ghost"
        size="icon"
        onClick={onClose}
        // The dialog is named by its own aria-label; naming the close button
        // after the dialog made it announce as the action that opens one.
        aria-label={t("actions.close")}
      >
        <X size={18} />
      </Button>
    </div>
  );
}
