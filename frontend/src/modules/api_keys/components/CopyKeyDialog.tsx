import { useState } from "react";

import { useAutoResetFlag } from "@/hooks/useAutoResetFlag";
import { useTranslation } from "react-i18next";
import { Copy, Check, AlertTriangle, Key } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Sheet } from "@/components/ui/Sheet";
import { copyText } from "@/lib/clipboard";
import type { ApiKeyCreated } from "../types";

interface CopyKeyDialogProps {
  apiKey: ApiKeyCreated;
  onClose: () => void;
}

export default function CopyKeyDialog({ apiKey, onClose }: CopyKeyDialogProps) {
  const { t } = useTranslation("api_keys");
  const { t: ct } = useTranslation("common");
  const [copied, copy] = useAutoResetFlag(2000);
  // The key is on screen once and cannot be recovered, so a copy that did
  // not land has to say how to get it out by hand rather than change the
  // button and leave the reader believing it.
  const [failed, setFailed] = useState(false);

  const handleCopy = async () => {
    if ((await copyText(apiKey.raw_key)) === "copied") {
      setFailed(false);
      copy();
    } else {
      setFailed(true);
    }
  };

  return (
    // The key is shown once and cannot be recovered — so neither Escape nor a
    // stray click on the backdrop may take it away.
    <Sheet
      open
      onClose={onClose}
      dismissible={false}
      aria-label={t("copyDialog.title")}
    >
      {/* Header */}
      <div className="flex items-center gap-3 p-5 border-b border-border">
        <div className="w-9 h-9 rounded-xl bg-primary-50 flex items-center justify-center shrink-0">
          <Key size={18} className="text-primary-600" />
        </div>
        <h2 className="text-base font-semibold text-on">
          {t("copyDialog.title")}
        </h2>
      </div>

      <div className="p-5 space-y-4 flex-1 overflow-y-auto">
        {/* Warning */}
        <div
          data-testid="api-key-warning"
          className="flex items-start gap-3 rounded-xl bg-amber-500/10 border border-amber-500/30 p-3.5"
        >
          <AlertTriangle
            size={16}
            className="text-on-warning mt-0.5 shrink-0"
          />
          <p className="text-sm text-on-secondary">{t("copyDialog.warning")}</p>
        </div>

        {/* Key display */}
        <div className="space-y-2">
          <div className="w-full rounded-xl bg-surface-inset border border-border px-4 py-3 min-h-[56px] flex items-center">
            <code className="text-sm font-mono text-on break-all select-all leading-relaxed">
              {apiKey.raw_key}
            </code>
          </div>
          <Button
            variant="outline"
            className="w-full"
            onClick={handleCopy}
            leftIcon={
              copied ? (
                <Check size={16} className="text-accent-500" />
              ) : (
                <Copy size={16} />
              )
            }
          >
            {copied ? t("copyDialog.copied") : t("copyDialog.copy")}
          </Button>
          {failed && (
            <p
              data-testid="copy-key-manual-hint"
              className="text-xs text-on-warning"
            >
              {ct("copy.selectManually")}
            </p>
          )}
        </div>
      </div>

      <div className="px-5 pb-5">
        <Button
          data-testid="api-key-dialog-close"
          variant="primary"
          className="w-full"
          onClick={onClose}
        >
          {t("copyDialog.done")}
        </Button>
      </div>
    </Sheet>
  );
}
