import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/Button";
import { Textarea } from "@/components/ui/Textarea";
import { ClipboardPaste, Loader2 } from "lucide-react";

interface ImportPastePanelProps {
  onParse: (text: string) => Promise<void>;
  isParsing: boolean;
}

export function ImportPastePanel({
  onParse,
  isParsing,
}: ImportPastePanelProps) {
  const { t } = useTranslation("warehouse");
  const [text, setText] = useState("");

  const handleParse = async () => {
    if (!text.trim()) return;
    await onParse(text);
  };

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2 text-sm text-on-secondary">
        <ClipboardPaste size={16} />
        <span>{t("import.pasteHint")}</span>
      </div>
      <Textarea
        className="w-full h-48 p-3 border border-border rounded-lg font-mono text-xs resize-y focus:outline-none focus:ring-2 focus:ring-primary-500"
        placeholder={t("import.pastePlaceholder")}
        value={text}
        onChange={(e) => setText(e.target.value)}
        spellCheck={false}
        aria-label={t("import.pasteTab")}
      />
      <div className="flex justify-end">
        <Button onClick={handleParse} disabled={!text.trim() || isParsing}>
          {isParsing ? (
            <Loader2 size={16} className="animate-spin" />
          ) : (
            <ClipboardPaste size={16} />
          )}
          {isParsing ? t("import.parsing") : t("import.parse")}
        </Button>
      </div>
    </div>
  );
}
