import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { Plus, FileDown, Upload } from "lucide-react";
import { Button, buttonVariants } from "@/components/ui/Button";
import { cn } from "@/lib/utils";

interface AssetListHeaderActionsProps {
  canWrite: boolean;
  onExport: () => void;
  onImport: () => void;
}

/**
 * The asset list's header: Export, Import and "Add asset" in one row on every
 * width. Below `sm:` Export and Import shrink to their icons (each keeps its
 * name for assistive technology) beside "Add asset", so three labelled buttons
 * no longer stack above the search.
 *
 * Export stays for a reader: it downloads what this account is already
 * reading. Import and Add do not — a reader used to fill either one to the end
 * and meet the refusal on submit.
 */
export function AssetListHeaderActions({
  canWrite,
  onExport,
  onImport,
}: AssetListHeaderActionsProps) {
  const { t } = useTranslation("equipment");
  const tools = [
    {
      id: "export",
      label: t("common:actions.export"),
      icon: <FileDown size={16} className="text-amber-600" />,
      onSelect: onExport,
    },
    ...(canWrite
      ? [
          {
            id: "import",
            label: t("import.button", "Import"),
            icon: <Upload size={16} />,
            onSelect: onImport,
          },
        ]
      : []),
  ];

  return (
    <div className="flex items-center justify-end gap-2 ml-auto min-w-0">
      {tools.map(({ id, label, icon, onSelect }) => (
        <Button
          key={id}
          variant="outline"
          size="sm"
          leftIcon={icon}
          onClick={onSelect}
          aria-label={label}
          title={label}
          className="shrink-0"
        >
          <span className="hidden sm:inline">{label}</span>
        </Button>
      ))}
      {canWrite && (
        <Link
          to="/equipment/add"
          className={cn(
            buttonVariants(),
            "min-w-0 flex-1 gap-2 sm:flex-none sm:w-auto",
          )}
        >
          <Plus size={16} />
          {t("dashboard.add_asset")}
        </Link>
      )}
    </div>
  );
}
