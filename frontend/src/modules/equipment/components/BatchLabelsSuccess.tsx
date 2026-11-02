import { useTranslation } from "react-i18next";
import { CheckCircle2, Download, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Card, CardContent } from "@/components/ui/Card";
import { SendToPrinterButton } from "@/modules/shared/components/SendToPrinterButton";
import type {
  PrintOptions,
  PrintTarget,
} from "@/modules/shared/lib/printQueue";

interface BatchLabelsSuccessProps {
  count: number;
  /** The new labels, for "Send to printer" beside the download. */
  printTarget: PrintTarget;
  printOptions?: PrintOptions;
  onDownload: () => void;
  isDownloading: boolean;
  onDone: () => void;
}

export function BatchLabelsSuccess({
  count,
  printTarget,
  printOptions,
  onDownload,
  isDownloading,
  onDone,
}: BatchLabelsSuccessProps) {
  const { t } = useTranslation("equipment");
  return (
    <Card>
      <CardContent className="pt-6 space-y-5 flex flex-col items-center text-center">
        <CheckCircle2 size={40} className="text-success-600" />
        <div className="space-y-1">
          <p className="text-base font-medium text-on">
            {t("bulk.labelsAssigned", {
              count,
            })}
          </p>
          <p className="text-sm text-on-muted">
            {t(
              "bulk.labelsReadyHint",
              "Your labels are ready to print as a single file.",
            )}
          </p>
        </div>
        <div className="flex flex-col sm:flex-row gap-3 w-full sm:w-auto">
          <Button
            type="button"
            onClick={onDownload}
            disabled={isDownloading}
            leftIcon={
              isDownloading ? (
                <Loader2 size={16} className="animate-spin" />
              ) : (
                <Download size={16} />
              )
            }
          >
            {t("bulk.downloadLabels", "Download labels (PNG)")}
          </Button>
          <SendToPrinterButton target={printTarget} options={printOptions} />
          <Button
            type="button"
            variant="outline"
            onClick={onDone}
            disabled={isDownloading}
          >
            {t("bulk.done", "Done")}
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
