import { useState, type ReactNode } from "react";
import { X, FileSpreadsheet, ArrowRight } from "lucide-react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { extractApiError } from "@/lib/errors";
import { Button } from "@/components/ui/Button";
import { Sheet, SheetActions, SheetFooter } from "@/components/ui/Sheet";
import { ImportUploadStep } from "./ImportUploadStep";
import { ImportMappingStep } from "./ImportMappingStep";
import { ImportProgressStep } from "./ImportProgressStep";
import type {
  ImportMapping,
  ImportOutcome,
  ImportPreviewRow,
  MappingField,
  SheetAnalysis,
} from "./types";

export interface MappingStepContext {
  headers: string[];
  mapping: ImportMapping;
  setMapping: (mapping: ImportMapping) => void;
  /** Per column, how many of the whole file's rows carry a value — a
   *  warning that reads the data, not only the mapping, needs it (a
   *  mapped column can be empty in every row — codes come only from
   *  printed labels). The preview rows would not do: they stop at five,
   *  and a sheet whose codes start below them is not an empty-coded
   *  sheet. */
  filledCounts: SheetAnalysis["filled_counts"];
}

export interface ImportWizardSheetProps<R extends ImportOutcome> {
  onClose: () => void;
  title: string;
  /** "XLSX / CSV" — the formats line under the title. */
  formats: string;
  fields: MappingField[];
  /** The field the import cannot run without (mapped to a column). */
  requiredField: string;
  /** Anything else the entity needs before it can run — a target picked, say. */
  canRun?: boolean;
  /** Headers and the first rows — the mapping step shows both. */
  analyze: (file: File) => Promise<SheetAnalysis>;
  suggest: (headers: string[]) => ImportMapping;
  run: (file: File, mapping: ImportMapping) => Promise<R>;
  texts: {
    analyzeFailed: string;
    importFailed: string;
    wait: string;
    added: (count: number) => string;
    /** The sentence under the title — `added` unless the entity counts
     *  something else beside it, an overwrite among them. */
    summary?: (result: R) => string;
    closeAndView: string;
  };
  secondaryUpload?: { label: string; hint: string };
  /** Beside the analyzed file name; a preset button, say. */
  mappingHeaderExtras?: (ctx: MappingStepContext) => ReactNode;
  /** Under the mapping grid: the entity's notes and options. */
  mappingExtras?: (ctx: MappingStepContext) => ReactNode;
  /** Between the counts and the errors: what the import founded. */
  resultExtras?: (result: R) => ReactNode;
}

type Step = "upload" | "mapping" | "processing" | "result";

/** The three steps every spreadsheet import walks: pick a file, map its
 *  columns, read the report. What a row becomes is the entity's business,
 *  handed in through `analyze`, `suggest` and `run`. */
export function ImportWizardSheet<R extends ImportOutcome>({
  onClose,
  title,
  formats,
  fields,
  requiredField,
  canRun = true,
  analyze,
  suggest,
  run,
  texts,
  secondaryUpload,
  mappingHeaderExtras,
  mappingExtras,
  resultExtras,
}: ImportWizardSheetProps<R>) {
  const { t } = useTranslation(["common"]);
  const [step, setStep] = useState<Step>("upload");
  const [file, setFile] = useState<File | null>(null);
  const [headers, setHeaders] = useState<string[]>([]);
  const [previewRows, setPreviewRows] = useState<ImportPreviewRow[]>([]);
  const [filledCounts, setFilledCounts] = useState<
    SheetAnalysis["filled_counts"]
  >({});
  const [mapping, setMapping] = useState<ImportMapping>({});
  const [importResult, setImportResult] = useState<R | null>(null);

  const handleFileUpload = async (selectedFile: File) => {
    setFile(selectedFile);
    try {
      const analysis = await analyze(selectedFile);
      setHeaders(analysis.headers);
      setPreviewRows(analysis.preview_rows);
      setFilledCounts(analysis.filled_counts);
      setMapping(suggest(analysis.headers));
      setStep("mapping");
    } catch (error) {
      toast.error(extractApiError(error, texts.analyzeFailed));
    }
  };

  const handleImport = async () => {
    if (!file || !mapping[requiredField] || !canRun) return;
    setStep("processing");
    try {
      setImportResult(await run(file, mapping));
      setStep("result");
    } catch (error) {
      // A gate refusal carries its reason and its remedy, written to be
      // read; this bare catch used to bury it under a generic toast and
      // every failure read the same.
      toast.error(extractApiError(error, texts.importFailed));
      setStep("mapping");
    }
  };

  const ctx: MappingStepContext = {
    headers,
    mapping,
    setMapping,
    filledCounts,
  };
  const summaryText =
    importResult && texts.summary ? texts.summary(importResult) : undefined;

  return (
    <Sheet
      open
      onClose={onClose}
      maxWidth="3xl"
      backdropOpacity={60}
      aria-label={title}
    >
      {/* Header */}
      <div className="p-8 border-b flex items-center justify-between bg-surface/50">
        <div className="flex items-center gap-4">
          <div className="p-3 bg-primary-600 text-white rounded-2xl">
            <FileSpreadsheet size={24} />
          </div>
          <div>
            <h2 className="text-xl font-semibold text-on tracking-tight">
              {title}
            </h2>
            <p className="text-xs text-on-secondary font-medium uppercase tracking-widest mt-0.5">
              {formats}
            </p>
          </div>
        </div>
        <Button
          variant="ghost"
          size="icon"
          onClick={onClose}
          aria-label={t("common:a11y.close")}
        >
          <X size={24} />
        </Button>
      </div>

      <div className="flex-1 overflow-y-auto p-8 custom-scrollbar">
        {step === "upload" && (
          <ImportUploadStep
            onFileSelect={handleFileUpload}
            secondaryUpload={secondaryUpload}
          />
        )}

        {step === "mapping" && (
          <ImportMappingStep
            file={file}
            headers={headers}
            fields={fields}
            mapping={mapping}
            previewRows={previewRows}
            onMappingChange={setMapping}
            headerExtras={mappingHeaderExtras?.(ctx)}
          >
            {mappingExtras?.(ctx)}
          </ImportMappingStep>
        )}

        {(step === "processing" || step === "result") && (
          <ImportProgressStep
            isProcessing={step === "processing"}
            importResult={importResult}
            waitText={texts.wait}
            addedText={texts.added}
            summaryText={summaryText}
          >
            {importResult && resultExtras?.(importResult)}
          </ImportProgressStep>
        )}
      </div>

      {/* Footer */}
      <SheetFooter>
        <SheetActions>
          {step === "mapping" && (
            <>
              <Button
                variant="ghost"
                onClick={() => setStep("upload")}
                className="uppercase text-[10px] tracking-[0.2em]"
              >
                {t("common:actions.back")}
              </Button>
              <Button
                onClick={handleImport}
                disabled={!mapping[requiredField] || !canRun}
              >
                <span>{t("common:import.processImport")}</span>
                <ArrowRight size={20} />
              </Button>
            </>
          )}
          {step === "result" && (
            <Button onClick={onClose}>{texts.closeAndView}</Button>
          )}
          {step === "upload" && (
            <Button
              variant="ghost"
              onClick={onClose}
              className="uppercase text-[10px] tracking-[0.2em]"
            >
              {t("common:actions.cancel")}
            </Button>
          )}
        </SheetActions>
      </SheetFooter>
    </Sheet>
  );
}
