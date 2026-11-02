import { Loader2, QrCode, Download, Sparkles } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";

interface StorageQrCodeFieldProps {
  shortCode: string;
  onShortCodeChange: (value: string) => void;
  labelShowDescription: boolean;
  onLabelShowDescriptionChange: (checked: boolean) => void;
  isGeneratingCode: boolean;
  onGenerateCode: () => void;
  onQrDownload: () => void;
}

/** QR code field for the storage edit sheet: short code input, generate /
 * download buttons, and the optional "show description on label" toggle. */
export function StorageQrCodeField({
  shortCode,
  onShortCodeChange,
  labelShowDescription,
  onLabelShowDescriptionChange,
  isGeneratingCode,
  onGenerateCode,
  onQrDownload,
}: StorageQrCodeFieldProps) {
  const { t } = useTranslation(["locations", "common"]);

  return (
    <div>
      <label
        htmlFor="storage-qr-code"
        className="block text-[10px] font-medium uppercase tracking-widest text-on-muted mb-1.5"
      >
        <span className="flex items-center gap-1.5">
          <QrCode size={11} />
          {t("locations:edit.qrCodeLabel")}
        </span>
      </label>
      <div className="flex gap-2">
        <Input
          id="storage-qr-code"
          type="text"
          value={shortCode}
          placeholder={t("locations:edit.qrCodePlaceholder")}
          onChange={(e) => onShortCodeChange(e.target.value.toUpperCase())}
          className="font-mono"
        />
        {!shortCode ? (
          <Button
            type="button"
            variant="outline"
            title={t("locations:edit.generateCodeLabel", {
              defaultValue: "Generate QR code",
            })}
            onClick={onGenerateCode}
            disabled={isGeneratingCode}
          >
            {isGeneratingCode ? (
              <Loader2 size={14} className="animate-spin" />
            ) : (
              <Sparkles size={14} />
            )}
            {t("locations:edit.generateCodeLabel", {
              defaultValue: "Generate",
            })}
          </Button>
        ) : (
          <Button
            type="button"
            variant="outline"
            title={t("locations:edit.downloadQrLabel", {
              defaultValue: "Download QR code",
            })}
            onClick={onQrDownload}
          >
            <Download size={14} />
            {t("locations:edit.downloadQrLabel")}
          </Button>
        )}
      </div>
      {shortCode && (
        <>
          <p className="text-xs text-on-muted mt-1.5 font-mono">
            QR → {shortCode}
          </p>
          <label className="flex items-center gap-2 mt-2 cursor-pointer">
            <input
              type="checkbox"
              checked={labelShowDescription}
              onChange={(e) => onLabelShowDescriptionChange(e.target.checked)}
              className="rounded border-border"
            />
            <span className="text-xs text-on-muted">
              {t("locations:edit.showDescriptionOnLabel")}
            </span>
          </label>
        </>
      )}
      {!shortCode && (
        <p className="text-xs text-amber-600 dark:text-amber-400 mt-1.5">
          {t("locations:edit.noCodeWarning", {
            defaultValue: "No QR code — QR download disabled until generated",
          })}
        </p>
      )}
    </div>
  );
}
