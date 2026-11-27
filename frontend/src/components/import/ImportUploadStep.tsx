import React from "react";
import { useTranslation } from "react-i18next";
import { Upload, Database, AlertCircle } from "lucide-react";
import { Button } from "@/components/ui/Button";

/** A second tile naming a known source (Grocy, say). Without `accept` it
 *  opens the sheet picker; with it, a picker of its own that hands the file
 *  to `onFileSelect` — for a source that is not a sheet (Grocy's database
 *  file). `note` says what the reader needs to know before choosing it. */
export interface SecondaryUpload {
  label: string;
  hint: string;
  note?: string;
  accept?: string;
  onFileSelect?: (file: File) => void;
}

interface ImportUploadStepProps {
  onFileSelect: (file: File) => void;
  secondaryUpload?: SecondaryUpload;
}

export function ImportUploadStep({
  onFileSelect,
  secondaryUpload,
}: ImportUploadStepProps) {
  const { t } = useTranslation(["common"]);
  const handleFileUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    const selectedFile = e.target.files?.[0];
    if (selectedFile) {
      onFileSelect(selectedFile);
    }
  };

  const openFilePicker = () => document.getElementById("import-file")?.click();
  const ownPicker = Boolean(
    secondaryUpload?.accept && secondaryUpload.onFileSelect,
  );
  const openSecondaryPicker = () =>
    document
      .getElementById(ownPicker ? "import-file-secondary" : "import-file")
      ?.click();

  // Said of a spreadsheet only: beside a source that is not one, it stands
  // under the sheet's tile rather than under both.
  const sheetNote = (
    <div className="bg-amber-50 p-6 rounded-3xl border border-amber-100 flex items-start gap-4">
      <AlertCircle className="text-amber-500 shrink-0 mt-1" size={20} />
      <div className="text-sm text-amber-800 leading-relaxed">
        <p className="font-medium mb-1 uppercase tracking-tight text-[10px]">
          {t("common:import.noteTitle")}
        </p>
        {t("common:import.noteBody")}
      </div>
    </div>
  );

  return (
    <div className="space-y-8 py-10">
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <div className="flex flex-col gap-4">
          {/* Generic upload button */}
          <Button
            size="content"
            variant="outline"
            onClick={openFilePicker}
            className="p-8 border border-dashed flex-col items-center gap-4"
          >
            <div className="w-16 h-16 bg-surface text-on-muted rounded-2xl flex items-center justify-center group-hover:bg-primary-600 group-hover:text-white transition-all">
              <Upload size={32} />
            </div>
            <div>
              <p className="font-semibold text-on">
                {t("common:import.genericFormat")}
              </p>
              <p className="text-xs text-on-muted font-medium mt-1">
                {t("common:import.genericFormatHint")}
              </p>
            </div>
          </Button>
          {ownPicker && sheetNote}
        </div>

        {secondaryUpload && (
          <div className="flex flex-col gap-4">
            <Button
              size="content"
              variant="outline"
              onClick={openSecondaryPicker}
              className="p-8 border border-dashed border-primary-100 flex-col items-center gap-4"
            >
              <div className="w-16 h-16 rounded-2xl flex items-center justify-center transition-all bg-primary-50 text-primary-400 group-hover:bg-primary-600 group-hover:text-white">
                <Database size={32} />
              </div>
              <div>
                <p className="font-semibold text-primary-600">
                  {secondaryUpload.label}
                </p>
                <p className="text-xs text-on-muted font-medium mt-1">
                  {secondaryUpload.hint}
                </p>
              </div>
            </Button>
            {secondaryUpload.note && (
              <p className="text-sm text-on-secondary">
                {secondaryUpload.note}
              </p>
            )}
          </div>
        )}
      </div>

      {/* Hidden file input */}
      <input
        id="import-file"
        type="file"
        accept=".xlsx,.xls,.csv"
        className="hidden"
        onChange={handleFileUpload}
        aria-label={t("common:import.genericFormat")}
      />
      {ownPicker && secondaryUpload && (
        <input
          id="import-file-secondary"
          type="file"
          accept={secondaryUpload.accept}
          className="hidden"
          onChange={(e) => {
            const chosen = e.target.files?.[0];
            // Cleared, so choosing the same file again reads it again.
            e.target.value = "";
            if (chosen) secondaryUpload.onFileSelect?.(chosen);
          }}
          aria-label={secondaryUpload.label}
        />
      )}

      {!ownPicker && sheetNote}
    </div>
  );
}
