import { useId, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { Camera, Minus, Plus, ScanLine, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { Input } from "@/components/ui/Input";
import { QuantityInput } from "@/components/ui/QuantityInput";
import { ScanCameraPanel } from "@/components/ui/ScanCameraPanel";
import { useUomPrecision } from "@/hooks/useUomPrecision";
import { formatQuantityLocalized } from "@/lib/i18nHelpers";
import type { ProductSearchResult } from "@/modules/warehouse/api/documents";
import type {
  LineFieldErrors,
  ReceiptDraftLine,
} from "@/modules/warehouse/components/documentFormShared";
import { useDocumentScanner } from "@/modules/warehouse/hooks/useDocumentScanner";
import { useProductSearch } from "@/modules/warehouse/hooks/useProductSearch";
import { formatDate } from "@/utils/formatters";

/** The product on the card, with the search row that knew where it stands. */
interface Candidate {
  line: ReceiptDraftLine;
  found?: ProductSearchResult;
}

interface PhoneLineByLineProps {
  /** The lines entered so far — the blank starting row is not one. */
  lines: ReceiptDraftLine[];
  /** Drawn under a line; return null for a line with nothing to add. */
  renderLineExtra?: (line: ReceiptDraftLine) => ReactNode;
  stockLocationId: string | null;
  /** The search may fold identical records into one row per shelf. */
  merge: boolean;
  /** A record picked from the search starts at all it holds (a move). */
  wholeRecord: boolean;
  lineErrors: LineFieldErrors;
  /** A location label scanned where a product was expected. */
  onLocationScanned?: (locationId: string, name: string) => void;
  onAdd: (line: ReceiptDraftLine) => void;
  onRemove: (key: string) => void;
}

function candidateFrom(
  result: ProductSearchResult,
  wholeRecord: boolean,
): Candidate {
  const available =
    result.available_quantity != null
      ? Number(result.available_quantity)
      : undefined;
  return {
    found: result,
    line: {
      _key: crypto.randomUUID(),
      item_id: result.item_id ?? undefined,
      product_template_id: result.product_template_id ?? undefined,
      name: result.name,
      brand: result.brand ?? undefined,
      barcode: result.barcode ?? undefined,
      sku: result.sku ?? undefined,
      image_url: result.image_url ?? undefined,
      quantity: wholeRecord && available ? available : 1,
      uom_id: result.uom_id ?? null,
      batch_number: "",
      expiry_date: "",
      notes: "",
      unit_price: "",
      tax_rate: "",
    },
  };
}

/** The card of the product in hand: how many, with buttons a thumb can hit. */
function CandidateCard({
  candidate,
  onChange,
  onConfirm,
  onCancel,
}: {
  candidate: Candidate;
  onChange: (quantity: number) => void;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  const { t } = useTranslation(["warehouse", "common"]);
  const { line } = candidate;
  const headingId = useId();
  const precision = useUomPrecision(line.uom_id);
  const step = line.uom_id ? precision.step : 1;
  const quantity = Number(line.quantity) || 0;
  const by = (direction: 1 | -1) =>
    Number(
      Math.max(0, quantity + direction * step).toFixed(precision.decimalPlaces),
    );

  return (
    <Card role="region" aria-labelledby={headingId} className="space-y-4 p-4">
      <div className="space-y-0.5">
        <h3 id={headingId} className="text-base font-semibold text-on">
          {line.name}
        </h3>
        {candidate.found?.location_name && (
          <p className="text-sm text-on-secondary">
            {t("action.phone.standsWithQuantity", {
              location: candidate.found.location_name,
              quantity: formatQuantityLocalized(
                t,
                candidate.found.available_quantity ?? 0,
                candidate.found.uom_symbol,
              ),
            })}
          </p>
        )}
      </div>
      <div className="flex items-center justify-center gap-3">
        <Button
          variant="outline"
          size="lg"
          aria-label={t("common:actions.decrease")}
          title={t("common:actions.decrease")}
          disabled={quantity <= 0}
          onClick={() => onChange(by(-1))}
        >
          <Minus size={20} aria-hidden="true" />
        </Button>
        <QuantityInput
          uomId={line.uom_id}
          label={t("action.phone.howMany", { name: line.name })}
          labelClassName="sr-only"
          value={line.quantity}
          onQuantityChange={(next) => onChange(next ?? 0)}
          className="text-center text-lg font-semibold"
          wrapperClassName="w-28"
        />
        <Button
          variant="outline"
          size="lg"
          aria-label={t("common:actions.increase")}
          title={t("common:actions.increase")}
          onClick={() => onChange(by(1))}
        >
          <Plus size={20} aria-hidden="true" />
        </Button>
      </div>
      <div className="flex flex-col gap-2">
        <Button size="lg" disabled={!(quantity > 0)} onClick={onConfirm}>
          {t("action.phone.add")}
        </Button>
        <Button variant="ghost" onClick={onCancel}>
          {t("common:form.cancel")}
        </Button>
      </div>
    </Card>
  );
}

/**
 * Goods entered one product at a time, the way a person on the floor works:
 * scan the code (or type a name and tap the product), set how many with big
 * buttons, add, and the field is ready for the next one. What is already on
 * the list stays below, each with a way to take it off again.
 */
export function PhoneLineByLine({
  lines,
  stockLocationId,
  merge,
  wholeRecord,
  lineErrors,
  renderLineExtra,
  onLocationScanned,
  onAdd,
  onRemove,
}: PhoneLineByLineProps) {
  const { t } = useTranslation(["warehouse", "common"]);
  const [candidate, setCandidate] = useState<Candidate | null>(null);
  const [query, setQuery] = useState("");
  const scanner = useDocumentScanner({
    onAddOrIncrementLine: (line) => setCandidate({ line }),
    onOpenQuickAdd: () => toast.warning(t("action.phone.notInStock")),
    stock: { locationId: stockLocationId },
    announceAdded: false,
    onLocationScanned,
  });
  const { results, isLoading, search, clearSearch } = useProductSearch({
    locationId: stockLocationId,
    stockOnly: true,
    merge,
  });

  const choose = (result: ProductSearchResult) => {
    setCandidate(candidateFrom(result, wholeRecord));
    setQuery("");
    clearSearch();
  };

  const confirm = () => {
    if (!candidate) return;
    onAdd(candidate.line);
    toast.success(
      t("action.phone.added", {
        name: candidate.line.name,
        quantity: candidate.line.quantity,
      }),
    );
    setCandidate(null);
  };

  return (
    <div className="space-y-3">
      {candidate ? (
        <CandidateCard
          candidate={candidate}
          onChange={(quantity) =>
            setCandidate({
              ...candidate,
              line: { ...candidate.line, quantity },
            })
          }
          onConfirm={confirm}
          onCancel={() => setCandidate(null)}
        />
      ) : (
        <Card className="space-y-3 p-4">
          <form
            onSubmit={(event) => {
              // A hardware scanner types the code and presses Enter.
              event.preventDefault();
              if (!query.trim()) return;
              scanner.handleCodeScanned(query.trim());
              setQuery("");
              clearSearch();
            }}
          >
            <Input
              label={t("action.phone.scanOrSearch")}
              value={query}
              onChange={(event) => {
                setQuery(event.target.value);
                void search(event.target.value);
              }}
              leftIcon={<ScanLine size={16} />}
              autoComplete="off"
              disabled={scanner.scanLoading}
            />
          </form>
          <Button
            variant="outline"
            size="lg"
            className="w-full"
            leftIcon={<Camera size={16} />}
            aria-pressed={scanner.scanOpen}
            onClick={() => {
              const next = !scanner.scanOpen;
              scanner.setScanOpen(next);
              if (next) scanner.restartCamera();
            }}
          >
            {scanner.scanOpen ? t("scan.close") : t("scan.open")}
          </Button>
          <ScanCameraPanel
            open={scanner.scanOpen}
            pinned
            scannerError={scanner.scannerError}
            isCameraActive={scanner.isCameraActive}
            isTorchOn={scanner.isTorchOn}
            onRetry={scanner.restartCamera}
            onToggleTorch={scanner.toggleTorch}
            onClose={() => scanner.setScanOpen(false)}
          />
          {query.trim() && !isLoading && results.length === 0 && (
            <p className="text-sm text-on-secondary">{t("picker.noResults")}</p>
          )}
          {results.length > 0 && (
            <ul className="space-y-2" aria-label={t("action.phone.results")}>
              {results.map((result) => (
                <li key={`${result.item_id}-${result.location_name}`}>
                  <Button
                    variant="outline"
                    size="row"
                    className="w-full flex-col items-start gap-0.5 rounded-lg p-3 text-left whitespace-normal"
                    onClick={() => choose(result)}
                  >
                    <span className="font-medium text-on">{result.name}</span>
                    {result.location_name && (
                      <span className="text-xs text-on-secondary">
                        {t("action.phone.standsWithQuantity", {
                          location: result.location_name,
                          quantity: formatQuantityLocalized(
                            t,
                            result.available_quantity ?? 0,
                            result.uom_symbol,
                          ),
                        })}
                      </span>
                    )}
                    {/* Two records of one product on one shelf differ by date. */}
                    {result.expiry_date && (
                      <span className="text-xs text-on-secondary">
                        {t("lines.expiryDate")}:{" "}
                        {formatDate(result.expiry_date)}
                      </span>
                    )}
                  </Button>
                </li>
              ))}
            </ul>
          )}
        </Card>
      )}

      {lines.length > 0 && (
        <Card className="p-0">
          <h3 className="border-b border-border px-4 py-3 text-sm font-semibold text-on">
            {t("action.phone.listTitle", { count: lines.length })}
          </h3>
          <ul className="divide-y divide-border">
            {lines.map((line) => {
              const error = lineErrors[line._key];
              return (
                <li
                  key={line._key}
                  className="flex items-center justify-between gap-3 px-4 py-3"
                >
                  <div className="min-w-0">
                    <p className="truncate text-sm font-medium text-on">
                      {line.name}
                    </p>
                    <p className="text-sm text-on-secondary">
                      {t("action.phone.lineQuantity", {
                        quantity: line.quantity,
                      })}
                    </p>
                    {(error?.name || error?.quantity) && (
                      <p className="text-xs text-on-danger">
                        {error.name ?? error.quantity}
                      </p>
                    )}
                    {renderLineExtra?.(line)}
                  </div>
                  <Button
                    variant="ghostDanger"
                    size="icon"
                    aria-label={t("action.phone.remove", { name: line.name })}
                    title={t("action.phone.remove", { name: line.name })}
                    onClick={() => onRemove(line._key)}
                  >
                    <Trash2 size={16} aria-hidden="true" />
                  </Button>
                </li>
              );
            })}
          </ul>
        </Card>
      )}
    </div>
  );
}
