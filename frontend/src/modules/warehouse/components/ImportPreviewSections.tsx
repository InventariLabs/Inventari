import { CheckCircle, AlertCircle } from "lucide-react";
import { formatQuantityValue } from "@/utils/formatters";
import type { components } from "@/types/api-generated";

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

export type ImportResult = components["schemas"]["DocumentImportLinesResponse"];

type TFunc = (key: string, options?: Record<string, unknown>) => string;

interface PreviewViewProps {
  sourceLabel: string;
  totalRows: number;
  headers: string[];
  mapping: ColumnMapping;
  previewRows: PreviewRow[];
  onChangeMapping: (field: keyof ColumnMapping, value: string) => void;
  columnMappingForm: React.ReactNode;
  createStubsForUnmatched: boolean;
  /** Founding templates is `items:write` work; without it the offer is
   *  withheld and the backend refuses the flag outright. */
  canCreateStubs: boolean;
  onToggleCreateStubs: (value: boolean) => void;
  t: TFunc;
}

export function ImportPreviewView({
  sourceLabel,
  totalRows,
  mapping,
  previewRows,
  onChangeMapping: _onChangeMapping,
  columnMappingForm,
  createStubsForUnmatched,
  canCreateStubs,
  onToggleCreateStubs,
  t,
}: PreviewViewProps) {
  return (
    <>
      <div className="flex items-center justify-between p-3 bg-surface-raised rounded-lg">
        <span className="text-sm font-medium truncate">{sourceLabel}</span>
        <span className="text-xs text-on-muted">
          {t("warehouse:import.rowCount", { count: totalRows })}
        </span>
      </div>

      <div className="space-y-3">
        <h3 className="text-sm font-semibold">
          {t("warehouse:import.columnMapping")}
        </h3>
        {columnMappingForm}
      </div>

      {canCreateStubs && (
        <label className="flex items-start gap-2 text-xs text-on-secondary cursor-pointer select-none">
          <input
            type="checkbox"
            checked={createStubsForUnmatched}
            onChange={(e) => onToggleCreateStubs(e.target.checked)}
            className="mt-0.5 h-4 w-4 rounded border-border text-primary-600 focus:ring-primary-500"
          />
          <span>
            <strong className="text-on font-medium">
              {t("warehouse:import.createStubsLabel")}
            </strong>
            <br />
            <span>{t("warehouse:import.createStubsHint")}</span>
          </span>
        </label>
      )}
      {!canCreateStubs && (
        <p className="text-xs text-on-secondary">
          {t("warehouse:import.createStubsDenied")}
        </p>
      )}

      {previewRows.length > 0 && (
        <div className="space-y-2">
          <h3 className="text-sm font-semibold">
            {t("warehouse:import.preview")}
          </h3>
          <div className="border border-border rounded-lg overflow-hidden">
            <table className="w-full text-xs">
              <thead className="bg-surface-raised">
                <tr>
                  <th scope="col" className="px-2 py-1 text-left">
                    #
                  </th>
                  <th scope="col" className="px-2 py-1 text-left">
                    {t("warehouse:import.name")}
                  </th>
                  <th scope="col" className="px-2 py-1 text-left">
                    {t("warehouse:import.barcode")}
                  </th>
                  <th scope="col" className="px-2 py-1 text-left">
                    {t("warehouse:import.quantity")}
                  </th>
                </tr>
              </thead>
              <tbody>
                {previewRows.slice(0, 5).map((row, idx) => (
                  <tr key={idx} className="border-t border-border">
                    <td className="px-2 py-1">{idx + 1}</td>
                    <td className="px-2 py-1">
                      {String(row[mapping.name] || "")}
                    </td>
                    <td className="px-2 py-1 font-mono">
                      {String(row[mapping.barcode] || "")}
                    </td>
                    <td className="px-2 py-1">
                      {String(row[mapping.quantity] || "1")}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </>
  );
}

interface ResultViewProps {
  result: ImportResult;
  t: TFunc;
}

export function ImportResultView({ result, t }: ResultViewProps) {
  return (
    <div className="space-y-4">
      <div className="flex items-center gap-4 p-4 bg-surface-raised rounded-lg">
        <div className="flex items-center gap-2">
          <CheckCircle size={20} className="text-accent-600" />
          <span className="text-sm font-medium">
            {t("warehouse:import.linesImported", { count: result.imported })}
          </span>
        </div>
        <div className="text-xs text-on-muted">
          {t("warehouse:import.matched", { count: result.matched })},{" "}
          {t("warehouse:import.unmatched", { count: result.unmatched })}
          {result.stubs_created > 0 && (
            <span className="ml-1 text-primary-700 dark:text-primary-300">
              ·{" "}
              {t("warehouse:import.stubsCreated", {
                count: result.stubs_created,
              })}
            </span>
          )}
        </div>
      </div>

      {result.errors.length > 0 && (
        <div className="p-3 bg-red-50 border border-red-200 rounded-lg">
          <div className="flex items-center gap-2 mb-2">
            <AlertCircle size={16} className="text-red-600" />
            <span className="text-sm font-medium text-red-700">
              {t("warehouse:import.errorCount", {
                count: result.errors.length,
              })}
            </span>
          </div>
          <ul className="text-xs text-red-600 space-y-1">
            {result.errors.slice(0, 5).map((err, idx) => (
              <li key={idx}>
                {t("warehouse:import.row")} {err.row}: {err.error}
              </li>
            ))}
          </ul>
        </div>
      )}

      {result.no_stock.length > 0 && (
        <div
          role="status"
          className="p-3 bg-amber-50 text-on-warning rounded-lg"
        >
          <div className="flex items-center gap-2 mb-2">
            <AlertCircle size={16} />
            <span className="text-sm font-medium">
              {t("warehouse:import.noStockCount", {
                count: result.no_stock.length,
              })}
            </span>
          </div>
          <p className="text-xs mb-1">{t("warehouse:import.noStockHint")}</p>
          <ul className="text-xs space-y-1">
            {result.no_stock.map((row) => (
              <li key={row.row}>
                {t("warehouse:import.row")} {row.row}: {row.name}
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="border border-border rounded-lg overflow-hidden">
        <table className="w-full text-xs">
          <thead className="bg-surface-raised">
            <tr>
              <th scope="col" className="px-2 py-1 text-left">
                #
              </th>
              <th scope="col" className="px-2 py-1 text-left">
                {t("warehouse:import.name")}
              </th>
              <th scope="col" className="px-2 py-1 text-left">
                {t("warehouse:import.brand")}
              </th>
              <th scope="col" className="px-2 py-1 text-left">
                {t("warehouse:import.barcode")}
              </th>
              <th scope="col" className="px-2 py-1 text-left">
                {t("warehouse:import.quantity")}
              </th>
              <th scope="col" className="px-2 py-1 text-left">
                {t("warehouse:import.template")}
              </th>
            </tr>
          </thead>
          <tbody>
            {result.lines.map((line, idx) => (
              <tr key={line.id} className="border-t border-border">
                <td className="px-2 py-1">{idx + 1}</td>
                <td className="px-2 py-1">{line.name}</td>
                <td className="px-2 py-1">{line.brand || "—"}</td>
                <td className="px-2 py-1 font-mono">{line.barcode || "—"}</td>
                <td className="px-2 py-1">
                  {formatQuantityValue(line.quantity)}
                </td>
                <td className="px-2 py-1">
                  {line.product_template_id ? (
                    <CheckCircle size={12} className="text-accent-600" />
                  ) : (
                    <span className="text-yellow-600">—</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
