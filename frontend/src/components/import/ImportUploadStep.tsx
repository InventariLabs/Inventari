import React from "react";
import { useTranslation } from "react-i18next";
import { Upload, Database, AlertCircle } from "lucide-react";
import { Button } from "@/components/ui/Button";

interface ImportUploadStepProps {
  onFileSelect: (file: File) => void;
  /** A second tile naming a known source (Grocy, say); opens the same picker. */
  secondaryUpload?: { label: string; hint: string };
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

  return (
    <div className="space-y-8 py-10">
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
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

        {secondaryUpload && (
          <Button
            size="content"
            variant="outline"
            onClick={openFilePicker}
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

      {/* Info box */}
      <div className="bg-amber-50 p-6 rounded-3xl border border-amber-100 flex items-start gap-4">
        <AlertCircle className="text-amber-500 shrink-0 mt-1" size={20} />
        <div className="text-sm text-amber-800 leading-relaxed">
          <p className="font-medium mb-1 uppercase tracking-tight text-[10px]">
            {t("common:import.noteTitle")}
          </p>
          {t("common:import.noteBody")}
        </div>
      </div>
    </div>
  );
}
