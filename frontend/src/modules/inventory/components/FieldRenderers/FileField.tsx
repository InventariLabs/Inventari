import { FileText, Download, X, Upload } from "lucide-react";
import { useTranslation } from "react-i18next";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/Button";
import { ATTACHMENT_FILE_ACCEPT } from "@/module-sdk";
import type { FieldDefinition } from "@/types";

interface FileFieldProps {
  /** Id the surrounding label points at — lands on the hidden file input. */
  id?: string;
  field: FieldDefinition;
  value: unknown;
  commonClasses: string;
  onFileSelect?: (fieldKey: string, file: File) => void;
  onChange: (value: unknown) => void;
}

export function FileField({
  id,
  field,
  value,
  commonClasses,
  onFileSelect,
  onChange,
}: FileFieldProps) {
  const { t } = useTranslation(["items", "common"]);
  const isUrl =
    value &&
    (String(value).startsWith("/uploads/") || String(value).startsWith("http"));

  if (isUrl) {
    const filename = String(value).split("/").pop() || String(value);
    const isPdf = filename.toLowerCase().endsWith(".pdf");

    return (
      <div
        className={cn(
          "flex items-center gap-1 rounded-xl border overflow-hidden transition-all",
          isPdf
            ? "bg-red-50/60 border-red-100"
            : "bg-violet-50/60 border-violet-100",
        )}
      >
        <a
          href={String(value)}
          target="_blank"
          rel="noopener noreferrer"
          className="flex items-center gap-2.5 flex-1 min-w-0 px-3 py-3 active:opacity-70"
          title={filename}
        >
          <FileText
            size={17}
            className={
              isPdf ? "text-red-500 shrink-0" : "text-violet-500 shrink-0"
            }
          />
          <span className="text-sm font-semibold text-on truncate">
            {filename}
          </span>
        </a>
        <a
          href={String(value)}
          download={filename}
          onClick={(e) => e.stopPropagation()}
          className="flex items-center justify-center w-11 h-11 text-on-muted hover:text-primary-600 active:bg-surface-card/60 rounded-lg transition-colors shrink-0"
          title={t("common:actions.download")}
        >
          <Download size={16} />
        </a>
        <Button
          type="button"
          variant="ghostDanger"
          size="icon"
          onClick={() => onChange("")}
          className="rounded-lg transition-colors shrink-0 mr-1"
          title={t("common:actions.delete")}
          aria-label={t("common:actions.remove")}
        >
          <X size={16} />
        </Button>
      </div>
    );
  }

  // Empty — show file picker
  const displayName = value ? String(value) : "";
  const inputId = id ?? `file-upload-${field.key}`;

  return (
    <div className="relative">
      <input
        id={inputId}
        type="file"
        className="sr-only"
        accept={ATTACHMENT_FILE_ACCEPT}
        onChange={(e) => {
          const file = e.target.files?.[0];
          if (file) {
            onChange(file.name);
            if (onFileSelect) onFileSelect(field.key, file);
          }
        }}
      />
      <label
        htmlFor={inputId}
        className={cn(
          commonClasses,
          "pl-11 pr-10 flex items-center cursor-pointer select-none",
        )}
      >
        <FileText
          className="absolute left-4 top-1/2 -translate-y-1/2 text-on-muted"
          size={18}
        />
        <span
          className={cn(
            "truncate",
            displayName ? "text-on" : "text-on-muted font-normal text-sm",
          )}
        >
          {displayName || t("items:placeholders.chooseFile")}
        </span>
        <Upload
          className="absolute right-3 top-1/2 -translate-y-1/2 text-on-muted hover:text-primary-500 transition-colors"
          size={16}
        />
      </label>
    </div>
  );
}
