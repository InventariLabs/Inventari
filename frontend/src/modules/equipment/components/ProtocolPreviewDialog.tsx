import { useTranslation } from "react-i18next";
import { Download } from "lucide-react";

import { Button } from "@/components/ui/Button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/Dialog";

interface Props {
  html: string | null;
  onClose: () => void;
  onDownloadPdf: () => void;
  downloading?: boolean;
}

/**
 * The handover protocol, shown as it will print — inside a sandbox.
 *
 * It used to open as a blob URL in a new tab. A blob inherits the origin of
 * the page that created it, so this document ran as the application: its
 * scripts could read the session and call the API as the reader. The HTML is
 * a Jinja layout an organization admin can edit, which makes "the reader is
 * also the author" an assumption rather than a guarantee.
 *
 * `sandbox=""` grants nothing back: no scripts, no forms, no same-origin.
 * Same as `TemplatePreviewFrame`, for the same reason.
 *
 * Which is also why the footer carries the download and there is no Print
 * button: `contentWindow.print()` is exactly the same-origin reach the
 * sandbox exists to deny, so the PDF is the route to paper. The description
 * said so for a release without a control to act on — the download sat back
 * in the row the reader had just left.
 */
export function ProtocolPreviewDialog({
  html,
  onClose,
  onDownloadPdf,
  downloading = false,
}: Props) {
  const { t } = useTranslation(["equipment", "common"]);

  return (
    <Dialog open={html !== null} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="w-full max-w-3xl max-h-[90vh] flex flex-col gap-0 p-0 overflow-hidden">
        <DialogHeader className="p-4 pb-3">
          <DialogTitle>
            {t("equipment:protocol.preview_html", "Print preview")}
          </DialogTitle>
          <DialogDescription>
            {t(
              "equipment:protocol.preview_hint",
              "Use the PDF download for a copy to print or send.",
            )}
          </DialogDescription>
        </DialogHeader>
        <iframe
          srcDoc={html ?? ""}
          title={t("equipment:protocol.preview_html", "Print preview")}
          className="w-full flex-1 min-h-[60vh] border-0 bg-white"
          sandbox=""
        />
        <DialogFooter className="p-4">
          <Button type="button" variant="outline" onClick={onClose}>
            {t("common:actions.close")}
          </Button>
          <Button
            type="button"
            leftIcon={<Download size={16} />}
            isLoading={downloading}
            onClick={onDownloadPdf}
          >
            {t("equipment:protocol.download_pdf", "Download PDF")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
