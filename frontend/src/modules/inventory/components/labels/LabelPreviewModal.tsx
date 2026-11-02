import { Download, Loader2, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import type { LabelPool } from "@/types";
import { Button } from "@/components/ui/Button";
import { Sheet } from "@/components/ui/Sheet";
import { useLabelSheetPreview } from "@/modules/inventory/hooks/useLabelSheetPreview";
import { LabelSettingsSidebar } from "./LabelSettingsSidebar";
import { SendToPrinterButton } from "@/modules/shared/components/SendToPrinterButton";

/**
 * Pixels the preview shows per millimetre of label.
 *
 * At 6 a standard 50×24 label filled a fifth of the panel it sits in — the
 * window is a preview and the preview was the smallest thing on it. The
 * image itself is the label at 300 dpi, about 12 pixels to the millimetre,
 * so at this scale the file shows nearly pixel for pixel.
 *
 * The image is scaled by the browser rather than `imageRendering: pixelated`.
 * Nearest-neighbour was drawing every source pixel as a hard block, and on a
 * 2x screen the panel asks for roughly twice the file's own resolution — so
 * each stair-step in a stroke came out doubled and the letters read as torn.
 */
const PREVIEW_PX_PER_MM = 12;

export interface PrintSettings {
  width: number;
  height: number;
  publicUrl: string;
  customDescription: string;
  qrOnly: boolean;
  copiesPerLabel: number;
  /** Print the short code beside the QR. Off by default — see the sidebar. */
  showCode: boolean;
}

interface LabelPreviewModalProps {
  open: boolean;
  onClose: () => void;
  selectedLabels: LabelPool[];
  printSettings: PrintSettings;
  setPrintSettings: React.Dispatch<React.SetStateAction<PrintSettings>>;
  onDownload: () => void;
}

export function LabelPreviewModal({
  open,
  onClose,
  selectedLabels,
  printSettings,
  setPrintSettings,
  onDownload,
}: LabelPreviewModalProps) {
  const { t } = useTranslation(["labels", "common"]);
  const [sheetPx, setSheetPx] = useState<{ w: number; h: number } | null>(null);
  // The action's name is the size of the operation. One pool row opens this
  // window and downloads one file named after that label's code; a checked
  // range downloads the batch. The count the words carry is the count the
  // download will produce — labels × copies, the same figure the sidebar
  // calls "Total labels to print".
  const totalCount = selectedLabels.length * printSettings.copiesPerLabel;
  const sheet = useLabelSheetPreview({
    labelIds: selectedLabels.map((label) => label.id),
    width: printSettings.width,
    height: printSettings.height,
    publicUrl: printSettings.publicUrl,
    description: printSettings.customDescription,
    qrOnly: printSettings.qrOnly,
    copiesPerLabel: printSettings.copiesPerLabel,
    showCode: printSettings.showCode,
    enabled: open,
  });

  // A pool label has no description until something is attached to it, and
  // the default content is the caption: the PNG came out as a bare QR with
  // nothing to read when it would not scan. Each time the window opens on a
  // label with no caption, the short code is selected too; the reader can
  // still choose otherwise.
  const lacksCaption = selectedLabels.some(
    (l) => !l.description && !l.assigned_item_name,
  );
  const wasOpen = useRef(open);
  useEffect(() => {
    if (open && !wasOpen.current) {
      setPrintSettings((prev) => ({ ...prev, showCode: lacksCaption }));
    }
    wasOpen.current = open;
  }, [open, lacksCaption, setPrintSettings]);

  if (!open) return null;

  return (
    <Sheet
      open={open}
      onClose={onClose}
      backdropOpacity={80}
      maxWidth="6xl"
      className="sm:max-w-4xl xl:max-w-6xl 3xl:max-w-7xl h-full max-h-[100dvh] sm:h-auto sm:max-h-[90vh] rounded-none sm:rounded-2xl bg-surface-raised"
      aria-label={t("previewModal.title", { count: totalCount })}
    >
      <div className="p-4 sm:p-6 bg-surface-card border-b border-border flex items-center justify-between shrink-0">
        <div>
          {/* Named for what the window does. It was called "Print
              preview" while its only exit was a PNG download — nothing here
              reaches a printer. */}
          <h2 className="text-xl font-semibold text-on">
            {t("previewModal.title", { count: totalCount })}
          </h2>
          <p className="text-sm text-on-secondary">
            {t("previewModal.subtitle")}
          </p>
        </div>
        <Button
          variant="ghost"
          size="icon"
          onClick={onClose}
          aria-label={t("common:actions.close")}
          className="p-2 hover:bg-surface-raised rounded-full text-on-muted"
        >
          <X size={24} />
        </Button>
      </div>

      <div className="flex-1 overflow-y-auto flex flex-col md:flex-row md:overflow-hidden">
        <LabelSettingsSidebar
          selectedLabels={selectedLabels}
          printSettings={printSettings}
          setPrintSettings={setPrintSettings}
          t={t}
        />

        {/* Preview area — the PNG the download produces, at the size the
            label really is. Drawing a second composition here is what let
            the two drift apart in the first place. */}
        <div className="flex-1 p-4 md:p-8 bg-surface-raised md:overflow-auto">
          <div className="flex flex-col items-center gap-3">
            {sheet.failed ? (
              <p className="text-sm text-on-muted py-10">
                {t("previewModal.previewFailed")}
              </p>
            ) : (
              <div className="w-full max-w-full overflow-x-auto">
                {/* Full width, or the `100%` inside the image's own width
                    would shrink-wrap to the image and nothing could ever
                    fill the panel. */}
                {sheet.url ? (
                  <img
                    key={sheet.url}
                    src={sheet.url}
                    alt={t("previewModal.sheetAlt")}
                    // The file's own dimensions decide the frame: one label
                    // of the sheet displays at the mm setting, the whole
                    // sheet takes that scale across its real width, and the
                    // height follows the aspect. Sizing the frame from the
                    // label settings alone was how a three-up tape sheet
                    // arrived as a thin strip swimming in an empty box.
                    onLoad={(e) => {
                      const el = e.currentTarget;
                      if (el.naturalWidth > 0 && el.naturalHeight > 0) {
                        setSheetPx({
                          w: el.naturalWidth,
                          h: el.naturalHeight,
                        });
                      }
                    }}
                    className="block mx-auto bg-white shadow-md border border-border"
                    style={
                      sheetPx
                        ? {
                            // The height cap rides inside the width as its
                            // px equivalent, so every clamp that bites keeps
                            // the aspect — capping height alone is what
                            // squashed sheets once the box stopped being
                            // honest about it. The panel's own width is the
                            // third clamp, as max-width rather than a `%`
                            // inside min(): the same box, in a form jsdom's
                            // CSS parser keeps instead of dropping.
                            width: `${Math.min(
                              Math.round(
                                (sheetPx.w *
                                  printSettings.height *
                                  PREVIEW_PX_PER_MM) /
                                  sheetPx.h,
                              ),
                              Math.round((420 * sheetPx.w) / sheetPx.h),
                            )}px`,
                            maxWidth: "100%",
                            height: "auto",
                            borderRadius: "2px",
                          }
                        : {
                            // One frame before the file's dimensions are
                            // known — the mm box is the best guess there is.
                            height: `${printSettings.height * PREVIEW_PX_PER_MM}px`,
                            width: "auto",
                            maxWidth: "100%",
                            maxHeight: "min(52vh, 420px)",
                            objectFit: "contain",
                            borderRadius: "2px",
                          }
                    }
                  />
                ) : (
                  <div
                    className="flex items-center justify-center text-on-muted"
                    style={{
                      height: `${printSettings.height * PREVIEW_PX_PER_MM}px`,
                      width: `${printSettings.width * PREVIEW_PX_PER_MM}px`,
                    }}
                  >
                    <Loader2 size={20} className="animate-spin" />
                  </div>
                )}
              </div>
            )}
            <span className="px-3 py-1 bg-gray-900 text-white text-[10px] font-medium rounded-full uppercase tracking-tighter">
              {printSettings.width}mm × {printSettings.height}mm
              {printSettings.copiesPerLabel > 1 && (
                <> · ×{printSettings.copiesPerLabel}</>
              )}
            </span>
            {sheet.isLoading && sheet.url && (
              <span className="text-[10px] text-on-muted uppercase tracking-wider">
                {t("previewModal.rerendering")}
              </span>
            )}
          </div>
        </div>
      </div>

      <div className="p-4 pb-20 sm:pb-6 md:p-6 bg-surface-card border-t border-border flex flex-col-reverse sm:flex-row sm:justify-end gap-3 md:gap-4 shrink-0">
        <Button variant="ghost" onClick={onClose} className="w-full sm:w-auto">
          {t("common:actions.close")}
        </Button>
        {/* The job carries this preview's size and content, so a printer
            gets the file on screen. Fitting it to the printer is the agent's
            job there; nothing about a printer changes the preview. */}
        <SendToPrinterButton
          target={{ labelIds: selectedLabels.map((label) => label.id) }}
          options={{
            caption: printSettings.customDescription || undefined,
            qrOnly: printSettings.qrOnly,
            showCode: printSettings.showCode,
            copies: printSettings.copiesPerLabel,
            width: printSettings.width,
            height: printSettings.height,
          }}
          className="w-full sm:w-auto"
          onSent={onClose}
        />
        <Button onClick={onDownload} className="w-full sm:w-auto">
          <Download size={20} />
          <span>{t("previewModal.downloadBatch", { count: totalCount })}</span>
        </Button>
      </div>
    </Sheet>
  );
}
