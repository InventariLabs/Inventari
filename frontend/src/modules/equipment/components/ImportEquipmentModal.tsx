import type { TFunction } from "i18next";
import { useState } from "react";
import { SheetActions } from "@/components/ui/Sheet";
import { useTranslation } from "react-i18next";
import { Loader2, Upload, Check, AlertCircle, FileDown } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Select } from "@/components/ui/Select";
import { ImportPreviewTable } from "@/components/import/ImportPreviewTable";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from "@/components/ui/Dialog";
import {
  equipmentApi,
  type ImportAnalyzeResult,
  type ImportExecuteResult,
} from "@/modules/equipment/api/equipment";
import { useEquipmentImportExecute } from "@/modules/equipment/hooks/useEquipment";
import { ImportResultSummary } from "@/modules/equipment/components/ImportResultSummary";
import { downloadBlob } from "@/utils/helpers";
import { extractApiError, isServerRefusal } from "@/lib/errors";
import { InlineQueryError } from "@/components/ui/QueryResult";
import { LocationCombobox } from "@/module-sdk";
import { useAllCategories } from "@/modules/shared/hooks/useCategories";
import { getCategoryLabel } from "@/modules/equipment/components/assetUtils";
import type { CategoryDTO } from "@/types";

type Step = "upload" | "mapping" | "processing" | "result";

/**
 * What a file can be mapped onto. Labels are keys, not literals: this is the
 * screen that teaches the import to read Polish column headers, and it used
 * to name its own targets in English while doing it.
 *
 * Brand and manufacturer are one fact about an asset, and the detail screen
 * shows one field — so there is one target, whichever of the two the file's
 * column is called.
 */
const EQUIPMENT_FIELDS = [
  { key: "name", labelKey: "import.fields.name", required: true },
  { key: "brand", labelKey: "import.fields.brand" },
  { key: "serial_number", labelKey: "import.fields.serial_number" },
  { key: "asset_tag", labelKey: "import.fields.asset_tag" },
  { key: "model", labelKey: "import.fields.model" },
  {
    key: "location",
    labelKey: "import.fields.location",
    required: true,
  },
  { key: "category", labelKey: "import.fields.category" },
  { key: "purchase_price", labelKey: "import.fields.purchase_price" },
  { key: "purchase_date", labelKey: "import.fields.purchase_date" },
  { key: "warranty_until", labelKey: "import.fields.warranty_until" },
  { key: "notes", labelKey: "import.fields.notes" },
  { key: "equipment_status", labelKey: "import.fields.equipment_status" },
];

/** A file with one row filled in, so the shape is obvious before uploading. */
function sampleCsv(headers: string[]): Blob {
  const example = [
    "Dell Latitude 5540",
    "Dell",
    "SN-000123",
    "IT-0001",
    "Latitude 5540",
    "Server Room",
    "",
    "4200",
    "2026-01-15",
    "2029-01-15",
    "",
    "AVAILABLE",
  ];
  const body = `${headers.join(",")}\n${example.slice(0, headers.length).join(",")}\n`;
  return new Blob([body], { type: "text/csv;charset=utf-8" });
}

interface ImportEquipmentModalProps {
  onClose: () => void;
}

// A 4xx says what is wrong with the file; a 5xx or no answer says nothing
// about it, and must not read as a verdict on a valid CSV.
function analyzeMessage(err: unknown, t: TFunction): string {
  return extractApiError(
    err,
    isServerRefusal(err)
      ? t("import.analyze_failed")
      : t("import.analyze_server_failed"),
  );
}

/**
 * One of the import's "default for rows that name none" pickers. A list that
 * failed to arrive must not read as "none to pick", so the select gives way to
 * a retry.
 */
function DefaultTargetSelect({
  label,
  value,
  onChange,
  options,
  error,
  onRetry,
}: {
  label: string;
  value: string;
  onChange: (id: string) => void;
  options: Array<{ id: string; name: string }>;
  error: unknown;
  onRetry: () => unknown;
}) {
  const { t } = useTranslation("equipment");
  return (
    <div className="flex-1">
      {error ? (
        <InlineQueryError error={error} onRetry={() => void onRetry()} />
      ) : (
        <Select
          label={label}
          value={value}
          onChange={onChange}
          placeholder={t("import.none", "-- None --")}
          options={options}
        />
      )}
    </div>
  );
}

export default function ImportEquipmentModal({
  onClose,
}: ImportEquipmentModalProps) {
  const { t } = useTranslation(["equipment", "common"]);
  const executeImport = useEquipmentImportExecute();
  const categories = useAllCategories();

  const equipmentCategories = (categories.data ?? []).filter(
    (c: CategoryDTO) => c.context_tag === "equipment",
  );

  const [step, setStep] = useState<Step>("upload");
  const [file, setFile] = useState<File | null>(null);
  const [analyzeResult, setAnalyzeResult] =
    useState<ImportAnalyzeResult | null>(null);
  const [mapping, setMapping] = useState<Record<string, string>>({});
  const [duplicateMode, setDuplicateMode] = useState<
    "create_only" | "update" | "duplicate"
  >("create_only");
  const [defaultLocationId, setDefaultLocationId] = useState("");
  const [defaultCategoryId, setDefaultCategoryId] = useState("");
  const [importResult, setImportResult] = useState<ImportExecuteResult | null>(
    null,
  );
  const [isProcessing, setIsProcessing] = useState(false);
  const [analyzeError, setAnalyzeError] = useState<string | null>(null);

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const selected = e.target.files?.[0];
    if (!selected) return;
    setFile(selected);
    // A new file is a new question; the old answer stops applying.
    setAnalyzeError(null);
  };

  const handleAnalyze = async () => {
    if (!file) return;
    setIsProcessing(true);
    setAnalyzeError(null);
    try {
      const result = await equipmentApi.analyzeImport(file);
      setAnalyzeResult(result);
      // the backend suggests mappings via aliases in all five
      // module languages — the frontend heuristics are no longer needed.
      setMapping(result.suggested_mapping ?? {});
      setStep("mapping");
    } catch (err) {
      // There was a `finally` here and no `catch`, so the rejected promise had
      // nowhere to go: the spinner stopped, the step did not move, and the
      // reader -- with no reason to think anything had gone wrong -- pressed
      // Analyze again.
      setAnalyzeError(analyzeMessage(err, t));
    } finally {
      setIsProcessing(false);
    }
  };

  const handleExecute = () => {
    if (!file) return;
    if (!mapping.name) return;
    setIsProcessing(true);
    executeImport.mutate(
      {
        file,
        // the duplicate policy travels inside the mapping payload.
        mapping: { ...mapping, duplicate_mode: duplicateMode },
        defaultLocationId: defaultLocationId || undefined,
        defaultCategoryId: defaultCategoryId || undefined,
      },
      {
        onSuccess: (result) => {
          setImportResult(result);
          setStep("result");
        },
        onSettled: () => {
          setIsProcessing(false);
        },
      },
    );
  };

  const handleClose = () => {
    onClose();
  };

  // ui/Dialog rather than a bespoke z-[100] overlay, so
  // the modal participates in the focus-trap + z-index token system used
  // by the rest of the module.
  return (
    <Dialog open onOpenChange={(open) => !open && handleClose()}>
      <DialogContent className="w-full max-w-md sm:max-w-xl lg:max-w-2xl xl:max-w-3xl gap-0 p-0 rounded-t-3xl sm:rounded-2xl max-h-[90vh] flex flex-col overflow-hidden">
        <DialogHeader className="px-5 py-4 border-b border-border">
          <DialogTitle className="flex items-center gap-3">
            <Upload size={18} className="text-primary-500" />
            {t("import.title", "Import Equipment from CSV / XLSX")}
          </DialogTitle>
          <DialogDescription>
            {t(
              "import.description",
              "Upload a spreadsheet to bulk-create assets.",
            )}
          </DialogDescription>
        </DialogHeader>

        <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4 space-y-4">
          {step === "upload" && (
            <>
              <label className="flex flex-col items-center justify-center gap-3 p-8 border border-dashed border-border rounded-lg cursor-pointer hover:border-primary-400 transition-colors">
                <Upload size={32} className="text-on-muted" />
                <span className="text-sm text-on-muted">
                  {t("import.drop_hint", "Click to select CSV or XLSX file")}
                </span>
                {file && (
                  <span className="text-sm font-medium text-on flex items-center gap-1.5">
                    <Check size={14} className="text-success-500" />
                    {file.name}
                  </span>
                )}
                <input
                  type="file"
                  accept=".csv,.xlsx,.xls"
                  className="hidden"
                  onChange={handleFileChange}
                />
              </label>

              {/* What the import can read, before anything is uploaded — the
                  screen used to answer that only after a file had been sent. */}
              <div className="rounded-lg border border-border p-3 space-y-2">
                <p className="text-sm font-medium text-on">
                  {t("import.supported_title")}
                </p>
                <div className="flex flex-wrap gap-1.5">
                  {EQUIPMENT_FIELDS.map((field) => (
                    <span
                      key={field.key}
                      className="inline-flex items-center rounded-md bg-surface-raised px-2 py-0.5 text-xs text-on-secondary"
                    >
                      {t(field.labelKey)}
                      {field.required && (
                        <span className="text-red-500 ml-0.5">*</span>
                      )}
                    </span>
                  ))}
                </div>
                <p className="text-xs text-on-muted">
                  {t("import.supported_hint")}
                </p>
                <p className="text-xs text-on-muted">
                  {t("import.location_path_hint")}
                </p>
                <Button
                  variant="ghost"
                  size="sm"
                  leftIcon={<FileDown size={14} />}
                  onClick={() =>
                    downloadBlob(
                      sampleCsv(EQUIPMENT_FIELDS.map((f) => t(f.labelKey))),
                      "equipment-import-template.csv",
                    )
                  }
                >
                  {t("import.template")}
                </Button>
              </div>

              {analyzeError && (
                <div
                  role="alert"
                  className="flex items-start gap-2 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700"
                >
                  <AlertCircle size={16} className="mt-0.5 shrink-0" />
                  <span>{analyzeError}</span>
                </div>
              )}

              <SheetActions>
                <Button variant="outline" onClick={handleClose}>
                  {t("common:form.cancel", "Cancel")}
                </Button>
                <Button
                  onClick={handleAnalyze}
                  disabled={!file || isProcessing}
                >
                  {isProcessing ? (
                    <Loader2 size={14} className="animate-spin mr-2" />
                  ) : (
                    <Upload size={14} className="mr-2" />
                  )}
                  {t("import.analyze", "Analyze")}
                </Button>
              </SheetActions>
            </>
          )}

          {step === "mapping" && analyzeResult && (
            <>
              <div className="text-sm text-on-muted">
                {t(
                  "import.rows_found",
                  "{{count}} rows found — map columns below",
                  {
                    count: analyzeResult.total_rows,
                  },
                )}
              </div>

              <div className="space-y-3 max-h-72 overflow-y-auto">
                {EQUIPMENT_FIELDS.map((field) => (
                  <div key={field.key} className="flex items-center gap-2">
                    <label
                      htmlFor={`import-map-${field.key}`}
                      className="block w-1/3 text-sm font-medium text-on-secondary"
                    >
                      {t(field.labelKey)}
                      {field.required && (
                        <span className="text-red-500 ml-0.5">*</span>
                      )}
                    </label>
                    <Select
                      id={`import-map-${field.key}`}
                      value={mapping[field.key] ?? ""}
                      onChange={(id) =>
                        setMapping((prev) => ({
                          ...prev,
                          [field.key]: id,
                        }))
                      }
                      placeholder={t("import.skip", "-- Skip --")}
                      options={analyzeResult.headers.map((h) => ({
                        id: h,
                        name: h,
                      }))}
                    />
                  </div>
                ))}
              </div>

              {/* What the mapping actually reads, on rows the reader can
                  see. The step used to show twelve dropdowns and not one
                  value, so a shifted header row looked correctly mapped. */}
              <ImportPreviewTable
                rows={analyzeResult.preview_rows}
                fields={EQUIPMENT_FIELDS.map((field) => ({
                  key: field.key,
                  label: t(field.labelKey),
                  required: field.required,
                }))}
                mapping={mapping}
              />

              <div className="flex gap-2">
                <div className="flex-1">
                  <LocationCombobox
                    label={t("import.default_location", "Default location")}
                    scope={{ contextTag: "equipment" }}
                    value={defaultLocationId}
                    onChange={setDefaultLocationId}
                    placeholder={t("import.none", "-- None --")}
                    title={t("import.default_location", "Default location")}
                    clearable
                    clearLabel={t("import.none", "-- None --")}
                  />
                </div>
                <DefaultTargetSelect
                  label={t("import.default_category", "Default category")}
                  value={defaultCategoryId}
                  onChange={setDefaultCategoryId}
                  // Built-in categories are seeded in English; the import
                  // target is named the way the category screen names it.
                  options={equipmentCategories.map((c) => ({
                    id: c.id,
                    name: getCategoryLabel(t, { code: c.code, name: c.name }),
                  }))}
                  error={categories.error}
                  onRetry={categories.refetch}
                />
              </div>

              {/* duplicate handling for rows whose serial number
                  already exists in the registry. */}
              <div>
                <Select
                  label={t("import.duplicateMode", "Duplicate serial numbers")}
                  value={duplicateMode}
                  onChange={(id) =>
                    setDuplicateMode(
                      id as "create_only" | "update" | "duplicate",
                    )
                  }
                  options={[
                    {
                      id: "create_only",
                      name: t(
                        "import.duplicateCreateOnly",
                        "Skip existing assets",
                      ),
                    },
                    {
                      id: "update",
                      name: t("import.duplicateUpdate", "Update existing"),
                    },
                    {
                      id: "duplicate",
                      name: t("import.duplicateAllow", "Create duplicates"),
                    },
                  ]}
                />
              </div>

              <SheetActions>
                <Button variant="outline" onClick={() => setStep("upload")}>
                  {t("common:actions.back", "Back")}
                </Button>
                <Button
                  onClick={handleExecute}
                  disabled={!mapping.name || isProcessing}
                >
                  {isProcessing ? (
                    <Loader2 size={14} className="animate-spin mr-2" />
                  ) : null}
                  {t("import.execute", "Import")}
                </Button>
              </SheetActions>
            </>
          )}

          {step === "result" && importResult && (
            <>
              <ImportResultSummary result={importResult} />

              <Button onClick={handleClose} className="w-full">
                {t("common:actions.close", "Close")}
              </Button>
            </>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}
