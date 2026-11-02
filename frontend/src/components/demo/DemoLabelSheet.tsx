import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Download, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/Button";
import {
  Sheet,
  SheetActions,
  SheetBody,
  SheetFooter,
  SheetHeader,
} from "@/components/ui/Sheet";
import { api } from "@/lib/api/client";
import { extractApiError } from "@/lib/errors";
import { downloadBlob } from "@/utils/helpers";

/**
 * The demo's own label sheet, one A4: this sandbox's shelves and a handful of
 * its products, as one PNG. The preview is the file the download gives —
 * print it once and the printed codes scan with a phone anywhere in the
 * demo, because the demo's seed gives the same shelves the same codes in
 * every sandbox.
 */
export function DemoLabelSheet({ onClose }: { onClose: () => void }) {
  const { t } = useTranslation(["auth", "common"]);
  const [url, setUrl] = useState<string | null>(null);
  const [file, setFile] = useState<Blob | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    let objectUrl: string | null = null;
    api
      .get<Blob>("/printing/demo-label-sheet", { responseType: "blob" })
      .then((response) => {
        if (cancelled) return;
        objectUrl = URL.createObjectURL(response.data);
        setFile(response.data);
        setUrl(objectUrl);
      })
      .catch((caught: unknown) => {
        if (cancelled) return;
        setError(extractApiError(caught, t("auth:demo.labelSheetFailed")));
      });
    return () => {
      cancelled = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [t]);

  const download = () => {
    if (file) downloadBlob(file, "demo-label-sheet.png");
  };

  const title = t("auth:demo.labelSheetTitle");
  return (
    <Sheet open onClose={onClose} maxWidth="3xl" aria-label={title}>
      <SheetHeader title={title} onClose={onClose} />
      <SheetBody className="p-5 space-y-5">
        <p className="text-sm text-on-muted">
          {t("auth:demo.labelSheetIntro")}
        </p>
        <div className="flex justify-center rounded-xl bg-surface-raised p-4 min-h-32">
          {error ? (
            <p className="text-sm text-on-muted self-center">{error}</p>
          ) : url ? (
            <img
              src={url}
              alt={t("auth:demo.labelSheetAlt")}
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
          <Button
            onClick={download}
            disabled={!file || Boolean(error)}
            leftIcon={<Download size={16} />}
          >
            {t("common:actions.download")}
          </Button>
        </SheetActions>
      </SheetFooter>
    </Sheet>
  );
}
