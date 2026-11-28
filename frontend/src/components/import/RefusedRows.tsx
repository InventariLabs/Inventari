import { Download } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/Button";
import type { components } from "@/types/api-generated";
import { downloadBlob } from "@/utils/helpers";

type RefusedRowsFile = components["schemas"]["RefusedRowsFile"];

const MEDIA_TYPES = {
  csv: "text/csv;charset=utf-8",
  xlsx: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
};

function download({ filename, content_base64 }: RefusedRowsFile) {
  const bytes = Uint8Array.from(atob(content_base64), (c) => c.charCodeAt(0));
  const type = filename.endsWith(".csv") ? MEDIA_TYPES.csv : MEDIA_TYPES.xlsx;
  downloadBlob(new Blob([bytes], { type }), filename);
}

interface Props {
  /** How many rows the import refused. */
  failed: number;
  /** How many of their reasons the screen lists above. */
  shown: number;
  /** Every refused row with its reason, as the server wrote it. */
  file?: RefusedRowsFile | null;
}

/** Under an import's list of refusals: how many there were when the list is
 *  shorter, and the refused rows as a file to correct and upload alone. */
export function RefusedRows({ failed, shown, file }: Props) {
  const { t } = useTranslation("common");
  return (
    <div className="space-y-2">
      {shown < failed && (
        <p className="text-xs text-on">
          {t("import.refusedShown", { shown, count: failed })}
        </p>
      )}
      {file && (
        <>
          <Button
            variant="outline"
            size="sm"
            leftIcon={<Download size={14} />}
            onClick={() => download(file)}
          >
            {t("import.refusedDownload")}
          </Button>
          <p className="text-xs text-on-muted">{t("import.refusedHint")}</p>
        </>
      )}
    </div>
  );
}
