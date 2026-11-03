import { useMemo, useState, type ReactNode } from "react";
import {
  Camera,
  CameraOff,
  Keyboard,
  Loader2,
  Package,
  Plus,
  Sparkles,
} from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { formatMoney } from "@/utils/formatters";
import { LineItemRow } from "./LineItemRow";
import type {
  LineItem,
  LineItemErrors,
  LineItemProduct,
  LineItemSearchState,
  LineItemsEditorFeatures,
  LineItemsEditorLabels,
  LineItemsEditorTestIds,
  LineItemsMode,
  LineItemsScanState,
  LineItemsTotals,
  RenderUomSelect,
} from "./types";

function ManualCodeEntry({
  onSubmit,
  label,
  placeholder,
  submit,
}: {
  onSubmit: (code: string) => void;
  label?: string;
  placeholder?: string;
  submit?: string;
}) {
  const [value, setValue] = useState("");

  const send = () => {
    const code = value.trim();
    if (!code) return;
    onSubmit(code);
    setValue("");
  };

  return (
    <div className="flex flex-col gap-2 bg-surface-card px-4 py-3 sm:flex-row sm:items-center">
      <span className="flex items-center gap-2 text-[10px] font-medium uppercase tracking-widest text-on-muted">
        <Keyboard size={14} />
        {label}
      </span>
      <Input
        type="text"
        data-testid="line-items-manual-code"
        wrapperClassName="sm:flex-1"
        value={value}
        onChange={(event) => setValue(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === "Enter") {
            event.preventDefault();
            send();
          }
        }}
        placeholder={placeholder}
        aria-label={label}
      />
      <Button type="button" variant="outline" size="sm" onClick={send}>
        {submit}
      </Button>
    </div>
  );
}

interface LineItemsEditorProps {
  lines: LineItem[];
  mode: LineItemsMode;
  features: LineItemsEditorFeatures;
  labels: LineItemsEditorLabels;
  search: LineItemSearchState;
  renderUomSelect: RenderUomSelect;
  scan?: LineItemsScanState;
  totals?: LineItemsTotals;
  totalsCurrency?: string | null;
  quickAddPanel?: ReactNode;
  dateLang?: string;
  formatLineValue?: (line: LineItem) => string;
  testIds?: LineItemsEditorTestIds;
  lineErrors?: Record<string, LineItemErrors>;
  onAddLine: () => void;
  onRemoveLine: (key: string) => void;
  onUpdateLine: (key: string, updates: Partial<LineItem>) => void;
  onSelectProduct: (key: string, product: LineItemProduct) => void;
  onConsolidate?: () => void;
  /** Drawn under each row; return null for a row with nothing to add. */
  renderLineExtra?: (line: LineItem) => ReactNode;
}

/**
 * Static grid-column literals for every supported feature combination.
 * Must stay as full literals — Tailwind JIT only generates classes it sees
 * verbatim in source, so runtime-composed `xl:grid-cols-[...]` strings are
 * silently dropped and the grid falls back to stacked full-width rows.
 */
const GRID_COLUMN_CLASSES = {
  "value:off,optional:off": "xl:grid-cols-[minmax(0,1fr)_110px_100px_40px]",
  "value:off,optional:on": "xl:grid-cols-[minmax(0,1fr)_110px_100px_40px_20px]",
  "value:on,tax:off,optional:off":
    "xl:grid-cols-[minmax(0,1fr)_110px_100px_110px_110px_40px]",
  "value:on,tax:off,optional:on":
    "xl:grid-cols-[minmax(0,1fr)_110px_100px_110px_110px_40px_20px]",
  "value:on,tax:on,optional:off":
    "xl:grid-cols-[minmax(0,1fr)_110px_100px_110px_90px_110px_40px]",
  "value:on,tax:on,optional:on":
    "xl:grid-cols-[minmax(0,1fr)_110px_100px_110px_90px_110px_40px_20px]",
} as const;

export function buildGridClass(features: LineItemsEditorFeatures): string {
  const variant = features.valueFields
    ? features.taxField
      ? "value:on,tax:on"
      : "value:on,tax:off"
    : "value:off";
  const optional = features.optionalFields ? "optional:on" : "optional:off";
  return GRID_COLUMN_CLASSES[`${variant},${optional}`];
}

export function LineItemsEditor({
  lines,
  mode,
  features,
  labels,
  search,
  renderUomSelect,
  scan,
  totals,
  totalsCurrency,
  quickAddPanel,
  dateLang = "en",
  formatLineValue,
  testIds,
  lineErrors,
  onAddLine,
  onRemoveLine,
  onUpdateLine,
  onSelectProduct,
  onConsolidate,
  renderLineExtra,
}: LineItemsEditorProps) {
  const [expandedOptional, setExpandedOptional] = useState<
    Record<string, boolean>
  >({});

  const gridClass = buildGridClass(features);

  const hasDuplicates = useMemo(() => {
    const seen = new Set<string>();
    for (const line of lines) {
      const id =
        line.item_id || line.product_template_id || line.name.trim() || null;
      if (!id) continue;
      const key = `${id}|${line.batch_number}|${line.expiry_date}|${line.unit_price}|${line.tax_rate}|${line.uom_id}`;
      if (seen.has(key)) return true;
      seen.add(key);
    }
    return false;
  }, [lines]);

  const isOptionalExpanded = (line: LineItem) =>
    expandedOptional[line.key] ??
    Boolean(line.batch_number || line.expiry_date || line.notes);

  const toggleOptional = (line: LineItem) => {
    setExpandedOptional((current) => ({
      ...current,
      [line.key]: !isOptionalExpanded(line),
    }));
  };

  const showTotals = features.totals && totals && Number(totals.subtotal) > 0;

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <p className="block text-xs font-medium uppercase text-on-secondary ml-1 tracking-wide">
          {labels.lines} *
        </p>
        <div className="flex items-center gap-2">
          {features.consolidate && hasDuplicates && onConsolidate && (
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={onConsolidate}
              className="text-amber-700 hover:text-amber-800 hover:bg-amber-50 dark:text-amber-400 dark:hover:bg-amber-950/20"
              leftIcon={<Sparkles size={14} />}
            >
              {labels.consolidate}
            </Button>
          )}
          {features.scan && scan && (
            <Button
              type="button"
              variant={scan.open ? "primary" : "ghost"}
              size="sm"
              onClick={scan.onToggle}
              className={scan.open ? "" : "text-on-secondary hover:text-on"}
              leftIcon={
                scan.loading ? (
                  <Loader2 size={14} className="animate-spin" />
                ) : scan.open ? (
                  <CameraOff size={14} />
                ) : (
                  <Camera size={14} />
                )
              }
            >
              {scan.open ? labels.scanClose : labels.scanOpen}
            </Button>
          )}
          <Button
            type="button"
            onClick={onAddLine}
            variant="ghost"
            size="sm"
            className="text-on-primary hover:underline"
            leftIcon={<Plus size={14} />}
          >
            {labels.addLine}
          </Button>
        </div>
      </div>

      <div
        data-testid={testIds?.shell}
        className="rounded-2xl border border-border bg-surface-card overflow-visible"
      >
        {features.scan && scan?.open && (
          <div className="border-b border-border bg-black relative">
            {scan.error ? (
              <div
                className="p-4 text-center text-sm text-red-400"
                data-testid="scan-error"
              >
                {scan.error}
              </div>
            ) : (
              <>
                {/* Torch and the processing badge are positioned against this
                    box, which holds only the video: against the black wrapper
                    they landed on the hint line and the manual-code row. The
                    one aim box is html5-qrcode's own qrbox — the only area
                    that decodes — so no second reticle is drawn. The camera
                    is a square (aspectRatio 1.0 in the hook), so a box as
                    wide as the dialog would be as tall as it and push the
                    manual-code row and the lines off the screen on a
                    desktop; narrowed and centred, the video stays uncropped
                    and the torch stays on its corner. */}
                <div
                  data-testid="scan-camera-box"
                  className="relative mx-auto w-full max-w-sm overflow-hidden"
                >
                  <div id="qr-reader" className="w-full" />
                  {scan.cameraActive ? (
                    <>
                      {scan.loading && (
                        <div
                          data-testid="scan-processing"
                          className="pointer-events-none absolute bottom-12 left-1/2 -translate-x-1/2 rounded-full bg-black/70 px-3 py-1 text-xs font-medium text-white"
                        >
                          {labels.scanProcessing ?? "Processing..."}
                        </div>
                      )}
                      {scan.torchAvailable && (
                        <Button
                          type="button"
                          variant="ghost"
                          size="sm"
                          onClick={scan.onToggleTorch}
                          className="absolute bottom-2 right-2 bg-black/60 text-white hover:bg-black/70"
                        >
                          {scan.torchOn ? labels.torchOff : labels.torchOn}
                        </Button>
                      )}
                    </>
                  ) : (
                    <div className="flex items-center justify-center py-10 text-xs uppercase tracking-widest text-on-muted">
                      <Loader2 size={14} className="mr-2 animate-spin" />
                      {labels.scanOpening ?? "Opening camera..."}
                    </div>
                  )}
                </div>
                <p className="text-center text-[10px] uppercase tracking-widest text-gray-400 py-1.5 bg-black">
                  {labels.scanHint}
                </p>
              </>
            )}
            {/* Reachable whether or not the camera is delivering — including
                the error branch above, which is exactly when a reader needs
                it most. */}
            {scan.onManualCode && (
              <ManualCodeEntry
                onSubmit={scan.onManualCode}
                label={labels.scanManualLabel}
                placeholder={labels.scanManualPlaceholder}
                submit={labels.scanManualSubmit}
              />
            )}
          </div>
        )}

        {features.quickAdd && quickAddPanel && (
          <div className="border-b border-border px-4 py-4">
            {quickAddPanel}
          </div>
        )}

        {lines.length === 0 ? (
          <div className="flex flex-col items-center gap-2 px-4 py-10 text-center">
            <Package size={28} className="text-on-muted" />
            <p className="text-sm text-on-secondary">{labels.emptyHint}</p>
          </div>
        ) : (
          <div className="xl:divide-y xl:divide-border/80">
            <div
              data-testid={testIds?.desktopHeader}
              className={`hidden border-b border-border bg-surface-raised/55 xl:grid xl:items-center xl:gap-3 xl:px-4 xl:py-2 ${gridClass}`}
            >
              <p className="text-[10px] font-medium uppercase tracking-widest text-on-muted">
                {labels.item}
              </p>
              <p className="text-[10px] font-medium uppercase tracking-widest text-on-muted">
                {labels.quantity}
              </p>
              <p className="text-[10px] font-medium uppercase tracking-widest text-on-muted">
                {labels.unit}
              </p>
              {features.valueFields && (
                <>
                  <p className="text-right text-[10px] font-medium uppercase tracking-widest text-on-muted">
                    {labels.unitPrice}
                  </p>
                  {features.taxField && (
                    <p className="text-right text-[10px] font-medium uppercase tracking-widest text-on-muted">
                      {labels.taxRate}
                    </p>
                  )}
                  <p className="text-right text-[10px] font-medium uppercase tracking-widest text-on-muted">
                    {labels.lineValue}
                  </p>
                </>
              )}
              {/* The remove column is an icon-only trash button; the full
                  "Remove line" label overflows the 40px cell and reads as a
                  merge of neighbouring headers. Keep it for screen readers. */}
              <p className="sr-only text-right text-[10px] font-medium uppercase tracking-widest text-on-muted">
                {labels.removeLine}
              </p>
              {features.optionalFields && <div />}
            </div>

            {lines.map((line, index) => (
              <LineItemRow
                key={line.key}
                line={line}
                index={index}
                mode={mode}
                features={features}
                labels={labels}
                search={search}
                renderUomSelect={renderUomSelect}
                gridClass={gridClass}
                isOptionalExpanded={isOptionalExpanded(line)}
                formatLineValue={formatLineValue}
                onToggleOptional={() => toggleOptional(line)}
                onUpdate={(updates) => onUpdateLine(line.key, updates)}
                onRemove={() => onRemoveLine(line.key)}
                onSelectProduct={(product) =>
                  onSelectProduct(line.key, product)
                }
                rowTestId={testIds?.rowLayout?.(index)}
                optionalPanelTestId={testIds?.optionalPanel?.(index)}
                error={lineErrors?.[line.key]}
                extra={renderLineExtra?.(line)}
              />
            ))}
          </div>
        )}

        {showTotals && (
          <div className="border-t border-border px-4 py-4">
            <div className="flex flex-col items-end gap-1 px-2">
              <div className="flex items-center gap-3">
                <span className="text-sm text-on-secondary">
                  {labels.subtotal}:
                </span>
                <span className="text-lg font-medium text-on">
                  {formatMoney(totals.subtotal, totalsCurrency, dateLang)}
                </span>
              </div>
              {Number(totals.tax) > 0 && (
                <div className="flex items-center gap-3">
                  <span className="text-sm text-on-secondary">
                    {labels.taxAmount}:
                  </span>
                  <span className="text-lg font-medium text-on">
                    {formatMoney(totals.tax, totalsCurrency, dateLang)}
                  </span>
                </div>
              )}
              <div className="flex items-center gap-3">
                <span className="text-sm text-on-secondary">
                  {labels.total}:
                </span>
                <span className="text-xl font-semibold text-on">
                  {formatMoney(totals.total, totalsCurrency, dateLang)}
                </span>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
