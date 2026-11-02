import { useState } from "react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/Button";
import { NativeSelect } from "@/components/ui/NativeSelect";
import { Sheet } from "@/components/ui/Sheet";
import type {
  BuiltInTemplate,
  TemplateUrlSegment,
} from "@/modules/shared/lib/templates";
import { TemplatePreviewFrame } from "@/modules/shared/components/TemplatePreviewFrame";

interface Props {
  open: boolean;
  onClose: () => void;
  templates: BuiltInTemplate[];
  /** Which module's templates API renders the preview. */
  module: TemplateUrlSegment;
}

/**
 * What a printed document looks like, before anyone has made one.
 *
 * The templates screen offered to copy built-in layouts and to write a new
 * one, and showed neither — so the only way to find out what the PDF would
 * contain was to generate a document and open it. The markup is rendered in
 * a sandboxed frame, exactly as the editor renders a draft.
 */
export function BuiltInTemplatePreview({
  open,
  onClose,
  templates,
  module,
}: Props) {
  const { t } = useTranslation(["warehouse", "common"]);
  const [selected, setSelected] = useState(0);
  const template = templates[selected];

  if (!open) return null;

  return (
    <Sheet
      open
      onClose={onClose}
      maxWidth="3xl"
      aria-labelledby="builtin-template-preview-title"
    >
      <>
        <div className="flex items-center justify-between p-4 border-b border-border">
          <h2
            id="builtin-template-preview-title"
            className="text-lg font-semibold text-on"
          >
            {t("templates.builtInPreviewTitle")}
          </h2>
          <Button
            variant="ghost"
            size="icon"
            onClick={onClose}
            aria-label={t("common:actions.close")}
            className="text-on-muted hover:text-on text-xl"
          >
            ×
          </Button>
        </div>

        <div className="flex-1 overflow-auto p-4 space-y-3">
          {templates.length > 1 && (
            <NativeSelect
              aria-label={t("templates.builtInPreviewTitle")}
              value={String(selected)}
              onChange={(e) => setSelected(Number(e.target.value))}
            >
              {templates.map((tpl, index) => (
                <option key={tpl.name} value={index}>
                  {tpl.name}
                </option>
              ))}
            </NativeSelect>
          )}
          <div className="rounded-lg border border-border bg-white p-2">
            <TemplatePreviewFrame
              module={module}
              bodyHtml={template?.body_html ?? ""}
              className="w-full h-[60vh] border-0"
            />
          </div>
        </div>
      </>
    </Sheet>
  );
}
