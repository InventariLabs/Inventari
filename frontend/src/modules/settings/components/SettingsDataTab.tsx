import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import { Download, Upload } from "lucide-react";
import { toast } from "sonner";

import { Card } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { itemsApi } from "@/lib/api/items";
import { useCanWrite } from "@/hooks/useCanWrite";
import { downloadBlob } from "@/utils/helpers";
import { getTodayFilename } from "@/utils/formatters";

export default function SettingsDataTab() {
  const { t } = useTranslation(["common"]);
  const navigate = useNavigate();
  // The bulk import writes products through the same `items:write` door the
  // single-product form asks for — a role that cannot add one product gets
  // no tile pointing at a wizard that would refuse every row.
  const canWriteItems = useCanWrite("items");

  const handleExport = async () => {
    try {
      toast.loading(t("common:actions.exporting"), { id: "export" });
      // The backup asks for everything, the list's usage default included.
      const response = await itemsApi.exportXlsx({ location_usage: "any" });
      downloadBlob(response, `inventari_export_${getTodayFilename()}.xlsx`);
      toast.success(t("common:actions.exportSuccess"), { id: "export" });
    } catch (err) {
      toast.error(t("common:actions.exportError"), { id: "export" });
    }
  };

  const handleImport = () => {
    // The import wizard exists — XLSX / CSV / Grocy, on the products list.
    // This card used to say "coming soon" about a feature two clicks away.
    navigate("/inventory/items?import=1");
  };

  return (
    <Card className="p-0 overflow-hidden sm:rounded-xl rounded-none">
      <div className="divide-y divide-border">
        <Button
          type="button"
          onClick={handleExport}
          variant="ghost"
          size="row"
          className="gap-4 px-4 py-4 rounded-none group"
        >
          <div className="w-9 h-9 rounded-xl bg-surface-raised flex items-center justify-center text-on-muted group-hover:text-accent-600 transition-colors shrink-0">
            <Download size={17} />
          </div>
          <div className="min-w-0 flex-1">
            <p className="text-sm font-medium text-on">
              {t("common:actions.export")}
            </p>
            <p className="text-xs text-on-muted mt-0.5">
              {t("settings.data.exportDesc")}
            </p>
          </div>
        </Button>

        {canWriteItems && (
          <Button
            type="button"
            onClick={handleImport}
            variant="ghost"
            size="row"
            className="gap-4 px-4 py-4 rounded-none group"
          >
            <div className="w-9 h-9 rounded-xl bg-surface-raised flex items-center justify-center text-on-muted group-hover:text-accent-600 transition-colors shrink-0">
              <Upload size={17} />
            </div>
            <div className="min-w-0 flex-1">
              <p className="text-sm font-medium text-on">
                {t("common:actions.import")}
              </p>
              <p className="text-xs text-on-muted mt-0.5">
                {t("settings.data.importDesc")}
              </p>
            </div>
          </Button>
        )}
      </div>
    </Card>
  );
}
