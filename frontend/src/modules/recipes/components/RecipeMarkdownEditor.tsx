import { useState, useRef } from "react";
import { useTranslation } from "react-i18next";
import ReactMarkdown from "react-markdown";
import rehypeSanitize from "rehype-sanitize";
import { InstructionsMarkdownToolbar } from "./InstructionsMarkdownToolbar";
import { Textarea } from "@/components/ui/Textarea";

interface Props {
  value: string;
  onChange: (value: string) => void;
}

export default function RecipeMarkdownEditor({ value, onChange }: Props) {
  const { t } = useTranslation("recipes");
  const [mdPreview, setMdPreview] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  function applyMarkdown(prefix: string, suffix: string, placeholder: string) {
    const el = textareaRef.current;
    if (!el) return;
    const start = el.selectionStart;
    const end = el.selectionEnd;
    const sel = el.value.slice(start, end) || placeholder;
    const next =
      el.value.slice(0, start) + prefix + sel + suffix + el.value.slice(end);
    onChange(next);
    requestAnimationFrame(() => {
      el.focus();
      el.setSelectionRange(
        start + prefix.length,
        start + prefix.length + sel.length,
      );
    });
  }

  function applyLinePrefix(linePrefix: string) {
    const el = textareaRef.current;
    if (!el) return;
    const pos = el.selectionStart;
    const lineStart = el.value.lastIndexOf("\n", pos - 1) + 1;
    const next =
      el.value.slice(0, lineStart) + linePrefix + el.value.slice(lineStart);
    onChange(next);
    requestAnimationFrame(() => {
      el.focus();
      el.setSelectionRange(pos + linePrefix.length, pos + linePrefix.length);
    });
  }

  return (
    <div>
      <p className="block text-sm font-medium text-on-secondary mb-1">
        {t("form.instructions")}
      </p>
      <InstructionsMarkdownToolbar
        attached
        mdPreview={mdPreview}
        onTogglePreview={() => setMdPreview((v) => !v)}
        onBold={() =>
          applyMarkdown("**", "**", t("import_export.md_placeholder_bold"))
        }
        onItalic={() =>
          applyMarkdown("*", "*", t("import_export.md_placeholder_italic"))
        }
        onHeading={() => applyLinePrefix("## ")}
        onBulletList={() => applyLinePrefix("- ")}
        onOrderedList={() => applyLinePrefix("1. ")}
        t={t}
      />
      {mdPreview ? (
        <div
          className="min-h-[200px] rounded-b-xl border border-border px-3 py-2.5 text-sm overflow-y-auto
          [&_h2]:text-base [&_h2]:font-semibold [&_h2]:mt-4 [&_h2]:mb-2
          [&_h3]:text-sm [&_h3]:font-semibold [&_h3]:mt-3 [&_h3]:mb-1
          [&_p]:mb-2 [&_p]:leading-relaxed
          [&_ul]:list-disc [&_ul]:pl-5 [&_ul]:mb-2
          [&_ol]:list-decimal [&_ol]:pl-5 [&_ol]:mb-2
          [&_li]:mb-1
          [&_strong]:font-semibold [&_em]:italic"
        >
          {value.trim() ? (
            <ReactMarkdown rehypePlugins={[rehypeSanitize]}>
              {value}
            </ReactMarkdown>
          ) : (
            <p className="text-on-muted italic">
              {t("import_export.md_empty")}
            </p>
          )}
        </div>
      ) : (
        <Textarea
          ref={textareaRef}
          aria-label={t("form.instructions")}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={t("form.instructions_placeholder")}
          rows={8}
          className="w-full rounded-b-xl border border-border bg-surface-card px-3 py-2.5 text-sm text-on placeholder:text-on-muted focus:outline-none focus:ring-2 focus:ring-primary-500 resize-y"
        />
      )}
      <p className="text-xs text-on-muted mt-1.5">
        {t("form.instructions_helper")}
      </p>
    </div>
  );
}
