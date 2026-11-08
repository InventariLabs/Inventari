import { extractApiError } from "@/lib/errors";
import { useCallback, useState } from "react";
import { useTranslation } from "react-i18next";
import { useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Button } from "@/components/ui/Button";
import { Sheet } from "@/components/ui/Sheet";
import {
  Tabs,
  TabsList,
  TabsTrigger,
  TabsContent,
  TabsPanels,
} from "@/components/ui/Tabs";
import { useHasPermission } from "@/hooks/useHasPermission";
import { api } from "@/lib/api/client";
import { invalidation } from "@/lib/api/invalidation";
import { validateFileSize } from "@/utils/fileValidation";
import { ClipboardPaste, Loader2, Upload, X } from "lucide-react";
import { ColumnMappingForm } from "./ColumnMappingForm";
import { ImportPastePanel } from "./ImportPastePanel";
import {
  type ImportResult,
  ImportPreviewView,
  ImportResultView,
} from "./ImportPreviewSections";

interface ColumnMapping {
  name: string;
  brand: string;
  barcode: string;
  sku: string;
  quantity: string;
  uom_symbol: string;
  unit_price: string;
  tax_rate: string;
  batch_number: string;
  expiry_date: string;
}

interface PreviewRow {
  [key: string]: string | number | null;
}

type SourceMode = "file" | "paste";

/** Where the lines go: into a saved draft, or back to a form with none yet. */
type ImportTarget =
  | { documentId: string }
  | {
      /** The type being written decides whether each line needs a stock record. */
      documentType: string;
      /** The shelf those records stand on. */
      sourceLocationId?: string;
    };

type DocumentImportModalProps = ImportTarget & {
  onClose: () => void;
  /** The import is done: a draft was written to (re-read it), or the lines
   *  in the result are the form's to add. */
  onImported?: (result: ImportResult) => void;
};

const EMPTY_MAPPING: ColumnMapping = {
  name: "",
  brand: "",
  barcode: "",
  sku: "",
  quantity: "",
  uom_symbol: "",
  unit_price: "",
  tax_rate: "",
  batch_number: "",
  expiry_date: "",
};

/** Header names a spreadsheet uses for each field, in the languages it arrives in. */
const HEADER_ALIASES: Record<keyof ColumnMapping, string[]> = {
  name: [
    "name",
    "product",
    "product name",
    "item",
    "item name",
    "nazwa",
    "produkt",
    "produktname",
    "nom",
    "désignation",
    "designation",
    "nombre",
    "producto",
  ],
  quantity: [
    "quantity",
    "qty",
    "received",
    "arrived",
    "qty received",
    "ilosc",
    "ilość",
    "ilosc przyjeta",
    "ilość przyjęta",
    "menge",
    "quantite",
    "quantité",
    "cantidad",
    "cantidad recibida",
  ],
  barcode: [
    "barcode",
    "ean",
    "kod kreskowy",
    "strichcode",
    "code barre",
    "codigo de barras",
    "código de barras",
  ],
  sku: [
    "sku",
    "code",
    "kod",
    "artikelnummer",
    "reference",
    "référence",
    "referencia",
  ],
  brand: ["brand", "marka", "hersteller", "marque", "marca"],
  uom_symbol: [
    "unit",
    "uom",
    "unit of measure",
    "jednostka",
    "einheit",
    "unite",
    "unité",
    "unidad",
  ],
  unit_price: [
    "price",
    "unit price",
    "cena",
    "cena netto",
    "preis",
    "prix",
    "precio",
  ],
  tax_rate: ["tax", "vat", "tax rate", "stawka vat", "mwst", "tva", "iva"],
  batch_number: [
    "batch",
    "lot",
    "batch number",
    "partia",
    "charge",
    "lot number",
    "lote",
  ],
  expiry_date: [
    "expiry",
    "expiry date",
    "best before",
    "data waznosci",
    "data ważności",
    "haltbarkeit",
    "peremption",
    "péremption",
    "caducidad",
  ],
};

/** Lowercase, accent-folded, single-spaced: "Data ważności" and "data waznosci" are one alias. */
function normalizeHeader(header: string): string {
  return header
    .normalize("NFD")
    .replace(/\p{Diacritic}/gu, "")
    .trim()
    .toLowerCase()
    .replace(/\s+/g, " ");
}

/**
 * The mapping a pasted or uploaded sheet arrives with.
 *
 * Readers paste "name, quantity" from a spreadsheet and expect the lines to
 * appear, not to teach the screen what a column called "quantity" is. The
 * guess is only a starting point: every select stays editable, and a header
 * the aliases do not know stays unmapped rather than being forced somewhere.
 */
export function guessMapping(headers: string[]): ColumnMapping {
  const normalized = headers.map(normalizeHeader);
  const used = new Set<number>();
  const mapping: ColumnMapping = { ...EMPTY_MAPPING };
  const order: Array<keyof ColumnMapping> = [
    "name",
    "quantity",
    "barcode",
    "sku",
    "uom_symbol",
    "unit_price",
    "tax_rate",
    "batch_number",
    "expiry_date",
    "brand",
  ];
  for (const field of order) {
    const aliases = HEADER_ALIASES[field];
    const index = normalized.findIndex(
      (header, position) => !used.has(position) && aliases.includes(header),
    );
    if (index < 0) continue;
    used.add(index);
    mapping[field] = headers[index];
  }
  return mapping;
}

interface AnalyzeResponse {
  headers: string[];
  preview_rows: PreviewRow[];
  total_rows: number;
}

/** The fields that tell the read-only endpoints which document the rows are for. */
function newDocumentFields(target: ImportTarget): Record<string, string> {
  if ("documentId" in target) return {};
  return {
    type: target.documentType,
    ...(target.sourceLocationId
      ? { source_location_id: target.sourceLocationId }
      : {}),
  };
}

export function DocumentImportModal(props: DocumentImportModalProps) {
  const { onClose, onImported } = props;
  const documentId = "documentId" in props ? props.documentId : undefined;
  const { t } = useTranslation(["warehouse", "common"]);
  const queryClient = useQueryClient();
  const [sourceMode, setSourceMode] = useState<SourceMode>("file");
  const [file, setFile] = useState<File | null>(null);
  const [pasteText, setPasteText] = useState<string>("");
  const [headers, setHeaders] = useState<string[]>([]);
  const [previewRows, setPreviewRows] = useState<PreviewRow[]>([]);
  const [totalRows, setTotalRows] = useState(0);
  const [mapping, setMapping] = useState<ColumnMapping>(EMPTY_MAPPING);
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [isImporting, setIsImporting] = useState(false);
  const [importResult, setImportResult] = useState<ImportResult | null>(null);
  const [createStubsForUnmatched, setCreateStubsForUnmatched] = useState(false);
  // Founding templates is items:write work (the backend refuses the flag
  // without it), so the offer to tick it is only shown to accounts the
  // permission would actually serve.
  const canCreateStubs = useHasPermission("items:write");

  const resetPreview = () => {
    setHeaders([]);
    setPreviewRows([]);
    setTotalRows(0);
    setMapping(EMPTY_MAPPING);
    setImportResult(null);
  };

  const applyAnalyzeResponse = (data: AnalyzeResponse) => {
    setHeaders(data.headers);
    setPreviewRows(data.preview_rows);
    setTotalRows(data.total_rows);
    setMapping(guessMapping(data.headers));
    setImportResult(null);
  };

  const handleFileChange = useCallback(
    async (event: React.ChangeEvent<HTMLInputElement>) => {
      const selectedFile = event.target.files?.[0];
      if (!selectedFile || !validateFileSize(selectedFile)) return;

      setFile(selectedFile);
      setPasteText("");
      setIsAnalyzing(true);
      resetPreview();
      try {
        const formData = new FormData();
        formData.append("file", selectedFile);
        const response = await api.post<AnalyzeResponse>(
          `/warehouse/import/analyze`,
          formData,
        );
        applyAnalyzeResponse(response.data);
      } catch (error) {
        // The file was not read: dropping it keeps "<name> — 0 rows" from
        // passing for an analysis of an empty file.
        setFile(null);
        toast.error(extractApiError(error, t("import.analyzeError")));
      } finally {
        setIsAnalyzing(false);
      }
    },
    [t],
  );

  const handleParsePaste = useCallback(
    async (text: string) => {
      setPasteText(text);
      setFile(null);
      setIsAnalyzing(true);
      resetPreview();
      try {
        const response = await api.post<AnalyzeResponse>(
          `/warehouse/import/parse-paste`,
          { text },
          { readOnly: true },
        );
        applyAnalyzeResponse(response.data);
      } catch (error) {
        setPasteText("");
        toast.error(extractApiError(error, t("import.parseError")));
      } finally {
        setIsAnalyzing(false);
      }
    },
    [t],
  );

  const handleDrop = useCallback(
    async (event: React.DragEvent<HTMLDivElement>) => {
      event.preventDefault();
      const droppedFile = event.dataTransfer.files?.[0];
      if (!droppedFile) return;
      const input = document.getElementById(
        "document-import-file-input",
      ) as HTMLInputElement;
      if (input) {
        const dt = new DataTransfer();
        dt.items.add(droppedFile);
        input.files = dt.files;
        input.dispatchEvent(new Event("change", { bubbles: true }));
      }
    },
    [],
  );

  const handleMappingChange = (field: keyof ColumnMapping, value: string) => {
    setMapping((prev) => ({ ...prev, [field]: value }));
  };

  const handleImport = async () => {
    // A sheet kept by code alone ("code,quantity") has no name column; the
    // backend finds the product by its SKU or barcode.
    const isValidMapping = [mapping.name, mapping.sku, mapping.barcode].some(
      (column) => column && headers.includes(column),
    );
    if (!isValidMapping) {
      toast.error(t("import.productColumnRequired"));
      return;
    }

    setIsImporting(true);
    try {
      let response;
      if (sourceMode === "file" && file) {
        if (!validateFileSize(file)) return;
        const formData = new FormData();
        formData.append("file", file);
        formData.append("mapping_json", JSON.stringify(mapping));
        if (createStubsForUnmatched && canCreateStubs) {
          formData.append("create_stubs_for_unmatched", "true");
        }
        for (const [key, value] of Object.entries(newDocumentFields(props))) {
          formData.append(key, value);
        }
        response = documentId
          ? await api.post<ImportResult>(
              `/warehouse/documents/${documentId}/import-lines`,
              formData,
            )
          : await api.post<ImportResult>(`/warehouse/import/lines`, formData);
      } else if (sourceMode === "paste" && pasteText) {
        const body = {
          text: pasteText,
          mapping_json: mapping,
          create_stubs_for_unmatched: createStubsForUnmatched && canCreateStubs,
          ...newDocumentFields(props),
        };
        response = documentId
          ? await api.post<ImportResult>(
              `/warehouse/documents/${documentId}/import-paste`,
              body,
            )
          : await api.post<ImportResult>(`/warehouse/import/lines/paste`, body);
      } else {
        return;
      }
      setImportResult(response.data);
      // The import is a write, through an endpoint of its own — nothing else
      // invalidated the document, so the card behind this sheet went on
      // saying "1 line, plan 5" over a document that now had three, until
      // somebody reloaded the page.
      if (documentId) invalidation.documents(queryClient, documentId);
      onImported?.(response.data);
      // "Imported 3 lines" counts rows the catalogue never matched: a reader
      // pasting a delivery of thirty rows with three misspelt codes would
      // hear success and post twenty-seven. Say what was matched, and what
      // was not, whenever any row was left behind.
      const { imported, matched, unmatched, failed } = response.data;
      if (unmatched > 0 || failed > 0) {
        const counts = [t("import.matched", { count: matched })];
        if (unmatched > 0) {
          counts.push(t("import.unmatched", { count: unmatched }));
        }
        if (failed > 0) {
          counts.push(t("import.errorCount", { count: failed }));
        }
        toast.warning(counts.join(" · "));
      } else {
        toast.success(t("import.success", { count: imported }));
      }
    } catch (error) {
      toast.error(extractApiError(error, t("import.error")));
    } finally {
      setIsImporting(false);
    }
  };

  const hasSource =
    (sourceMode === "file" && file) || (sourceMode === "paste" && pasteText);

  const sourceLabel =
    sourceMode === "file"
      ? (file?.name ?? "")
      : pasteText
        ? t("import.rowCount", {
            count: pasteText.split("\n").filter((l) => l.trim()).length,
          })
        : "";

  return (
    <Sheet
      open
      onClose={onClose}
      maxWidth="3xl"
      backdropOpacity={60}
      aria-label={t("import.title")}
    >
      <div className="flex items-center justify-between p-4 border-b border-border">
        <h2 className="text-lg font-semibold">{t("import.title")}</h2>
        <Button
          variant="ghost"
          size="icon"
          onClick={onClose}
          aria-label={t("common:actions.close")}
        >
          <X size={20} />
        </Button>
      </div>

      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {!hasSource && !importResult ? (
          <Tabs
            defaultValue="file"
            value={sourceMode}
            onValueChange={(v) => setSourceMode(v as SourceMode)}
          >
            <TabsList className="w-full">
              <TabsTrigger value="file" className="flex-1">
                <Upload size={16} className="mr-2" />
                {t("import.fileTab")}
              </TabsTrigger>
              <TabsTrigger value="paste" className="flex-1">
                <ClipboardPaste size={16} className="mr-2" />
                {t("import.pasteTab")}
              </TabsTrigger>
            </TabsList>
            {/* One shared cell: the paste tab was 120px taller than the file
                tab and the sheet jumped, centred, on every switch. */}
            <TabsPanels className="mt-4">
              <TabsContent value="file" stacked className="mt-0">
                <div
                  className="border border-dashed border-border rounded-xl p-8 text-center cursor-pointer hover:border-primary-300 transition-colors"
                  onDragOver={(e) => e.preventDefault()}
                  onDrop={handleDrop}
                  onClick={() =>
                    document
                      .getElementById("document-import-file-input")
                      ?.click()
                  }
                >
                  <Upload size={48} className="mx-auto text-on-muted mb-4" />
                  <p className="text-on-secondary">{t("import.dropFile")}</p>
                  <input
                    id="document-import-file-input"
                    type="file"
                    accept=".csv,.xlsx,.xls"
                    className="hidden"
                    onChange={handleFileChange}
                  />
                </div>
              </TabsContent>
              <TabsContent value="paste" stacked className="mt-0">
                <ImportPastePanel
                  onParse={handleParsePaste}
                  isParsing={isAnalyzing}
                />
              </TabsContent>
            </TabsPanels>
          </Tabs>
        ) : importResult ? (
          <ImportResultView result={importResult} t={t} />
        ) : (
          <ImportPreviewView
            sourceLabel={sourceLabel}
            totalRows={totalRows}
            headers={headers}
            mapping={mapping}
            previewRows={previewRows}
            onChangeMapping={handleMappingChange}
            columnMappingForm={
              <ColumnMappingForm
                mapping={mapping}
                headers={headers}
                onChange={handleMappingChange}
              />
            }
            createStubsForUnmatched={createStubsForUnmatched}
            canCreateStubs={canCreateStubs}
            onToggleCreateStubs={setCreateStubsForUnmatched}
            t={t}
          />
        )}
      </div>

      <div className="flex items-center justify-end gap-2 p-4 border-t border-border">
        <Button variant="outline" onClick={onClose}>
          {importResult ? t("import.close") : t("common:form.cancel")}
        </Button>
        {!importResult && (
          <Button
            onClick={handleImport}
            disabled={
              !hasSource ||
              !(mapping.name || mapping.sku || mapping.barcode) ||
              isAnalyzing ||
              isImporting
            }
            isLoading={isImporting}
          >
            {isImporting ? (
              <Loader2 size={16} className="animate-spin" />
            ) : null}
            {t("import.import")}
          </Button>
        )}
      </div>
    </Sheet>
  );
}
