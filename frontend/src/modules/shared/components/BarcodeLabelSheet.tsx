import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Download, Loader2 } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/Button";
import { Checkbox } from "@/components/ui/Checkbox";
import { Input } from "@/components/ui/Input";
import {
  Sheet,
  SheetActions,
  SheetBody,
  SheetFooter,
  SheetHeader,
} from "@/components/ui/Sheet";
import { extractApiError } from "@/lib/errors";
import { useSettingsStore } from "@/store/settingsStore";
import { downloadBlob } from "@/utils/helpers";
import { SendToPrinterButton } from "@/modules/shared/components/SendToPrinterButton";
import {
  fetchBarcodeLabels,
  useBarcodeLabelPreview,
  type BarcodeLabelOptions,
  type BarcodeLabelTarget,
} from "@/modules/shared/hooks/useBarcodeLabelPreview";

/** The pool's wide sizes: a label with bars carries a line of text and a 1D
 *  code. */
const PRESETS = [
  { word: "previewModal.preset.standard", width: 50, height: 24 },
  { word: "previewModal.preset.large", width: 62, height: 29 },
] as const;

interface BarcodeLabelSheetProps {
  target: BarcodeLabelTarget;
  onClose: () => void;
}

/**
 * Labels with bars for a selection — products', or shelves' with the code
 * large in Code 128: the preview is the file the download gives, and "Send to
 * printer" queues the same labels for an agent.
 */
export function BarcodeLabelSheet({ target, onClose }: BarcodeLabelSheetProps) {
  const { t } = useTranslation(["labels", "common"]);
  const defaultWidth = useSettingsStore((s) => s.defaultLabelWidth);
  const defaultHeight = useSettingsStore((s) => s.defaultLabelHeight);
  const [options, setOptions] = useState<BarcodeLabelOptions>({
    width: defaultWidth,
    height: defaultHeight,
    copies: 1,
    details: true,
    qr: false,
  });
  const [downloading, setDownloading] = useState(false);
  const shelves = "storageIds" in target;
  const count = shelves ? target.storageIds.length : target.itemIds.length;
  const preview = useBarcodeLabelPreview(
    target,
    options,
    t("labels:previewModal.previewFailed"),
  );
  const printable = (count - preview.withoutCode) * options.copies;
  // Spelled out, not built: the i18n gate reads the keys a file names.
  const title = shelves
    ? t("labels:locationLabel.title")
    : t("labels:productLabel.title");

  const download = async () => {
    setDownloading(true);
    try {
      const { blob } = await fetchBarcodeLabels(target, options);
      downloadBlob(blob, shelves ? "shelf-labels.png" : "product-labels.png");
    } catch (error) {
      toast.error(extractApiError(error, t("labels:errorDownloading")));
    } finally {
      setDownloading(false);
    }
  };

  const setSize = (key: "width" | "height", raw: string) =>
    setOptions((o) => ({ ...o, [key]: parseFloat(raw) || 0 }));

  return (
    <Sheet open onClose={onClose} maxWidth="3xl" aria-label={title}>
      <SheetHeader title={title} onClose={onClose} />
      <SheetBody className="p-5 space-y-5">
        <div className="flex flex-wrap gap-2">
          {PRESETS.map((preset) => (
            <Button
              key={preset.word}
              size="sm"
              variant={
                options.width === preset.width &&
                options.height === preset.height
                  ? "default"
                  : "outline"
              }
              onClick={() =>
                setOptions((o) => ({
                  ...o,
                  width: preset.width,
                  height: preset.height,
                }))
              }
            >
              {`${t(`labels:${preset.word}`)} ${preset.width}×${preset.height}`}
            </Button>
          ))}
        </div>
        <div className="grid grid-cols-3 gap-3 items-end">
          <Input
            label={`${t("labels:previewModal.width")} (mm)`}
            type="number"
            value={options.width}
            onChange={(e) => setSize("width", e.target.value)}
          />
          <Input
            label={`${t("labels:previewModal.height")} (mm)`}
            type="number"
            value={options.height}
            onChange={(e) => setSize("height", e.target.value)}
          />
          <Input
            label={t("labels:previewModal.copies")}
            type="number"
            min={1}
            max={20}
            value={options.copies}
            onChange={(e) =>
              setOptions((o) => ({
                ...o,
                copies: Math.min(
                  20,
                  Math.max(1, parseInt(e.target.value) || 1),
                ),
              }))
            }
          />
        </div>
        {shelves ? (
          <Checkbox
            id="location-label-qr"
            label={t("labels:locationLabel.qr")}
            checked={options.qr}
            onChange={(e) =>
              setOptions((o) => ({ ...o, qr: e.target.checked }))
            }
          />
        ) : (
          <div className="space-y-1">
            <Checkbox
              id="product-label-details"
              label={t("labels:productLabel.details")}
              checked={options.details && preview.withDetails !== 0}
              disabled={preview.withDetails === 0}
              onChange={(e) =>
                setOptions((o) => ({ ...o, details: e.target.checked }))
              }
            />
            {preview.withDetails === 0 && (
              <p className="text-sm text-on-muted">
                {t("labels:productLabel.noDetails")}
              </p>
            )}
          </div>
        )}
        {preview.withoutCode > 0 && (
          <p className="text-sm text-on-warning bg-amber-100 rounded-lg px-3 py-2">
            {shelves
              ? t("labels:locationLabel.withoutCode", {
                  count: preview.withoutCode,
                })
              : t("labels:productLabel.withoutCode", {
                  count: preview.withoutCode,
                })}
          </p>
        )}
        <div className="flex justify-center rounded-xl bg-surface-raised p-4 min-h-32">
          {preview.error ? (
            <p className="text-sm text-on-muted self-center">{preview.error}</p>
          ) : preview.url ? (
            <img
              src={preview.url}
              alt={
                shelves
                  ? t("labels:locationLabel.previewAlt")
                  : t("labels:productLabel.previewAlt")
              }
              className="block max-w-full h-auto bg-white shadow-md border border-border"
            />
          ) : (
            <Loader2
              size={20}
              className="animate-spin text-on-muted self-center"
            />
          )}
        </div>
      </SheetBody>
      <SheetFooter>
        <SheetActions>
          <Button variant="ghost" onClick={onClose}>
            {t("common:actions.close")}
          </Button>
          <SendToPrinterButton
            target={preview.error ? null : target}
            options={{
              copies: options.copies,
              width: options.width,
              height: options.height,
              ...(shelves
                ? { bars: true, qr: options.qr }
                : { details: options.details }),
            }}
            onSent={onClose}
          />
          <Button
            onClick={download}
            isLoading={downloading}
            disabled={Boolean(preview.error) || printable <= 0}
            leftIcon={<Download size={16} />}
          >
            {t("labels:previewModal.downloadBatch", { count: printable })}
          </Button>
        </SheetActions>
      </SheetFooter>
    </Sheet>
  );
}
