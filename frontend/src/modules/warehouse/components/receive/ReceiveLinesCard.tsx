import type { RefObject } from "react";
import { useTranslation } from "react-i18next";
import { ClipboardPaste } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import type { RegisterBeforeSubmit } from "@/lib/moduleRegistry";
import type { PutawayPreviewLine } from "@/modules/warehouse/api/putaway";
import type { ProductSearchResult } from "@/modules/warehouse/api/documents";
import { ReceiveLineRow } from "./ReceiveLineRow";
import { ReceiveScanField } from "./ReceiveScanField";
import type { ReceiveDraftLine, RowPatch } from "./receiveDraft";

interface Props {
  /** Handed to other modules' fields on each row. */
  registerBeforeSubmit: RegisterBeforeSubmit;
  lines: ReceiveDraftLine[];
  /** What the reader can do on an empty sheet: a delivery may wait on an
   *  order, a return and an internal receipt have none. */
  emptyHint: string;
  plans: Map<string, PutawayPreviewLine>;
  planFetching: boolean;
  showPrices: boolean;
  /** The profile's VAT handling: "NONE" hides the rate beside the price. */
  taxHandling: string;
  canWrite: boolean;
  focusLineKey: string | null;
  /** Rows of an order line whose delivered rows together fall short. */
  shortKeys: Set<string>;
  /** Rows the server refused for want of an expiry date. */
  undatedKeys: Set<string>;
  scanRef: RefObject<HTMLInputElement>;
  onSelectProduct: (product: ProductSearchResult) => void;
  onFocusHandled: () => void;
  onUpdate: (key: string, patch: RowPatch) => void;
  onRemove: (key: string) => void;
  onQuantityEnter: (index: number) => void;
  onOpenImport: () => void;
  onTogglePrices: () => void;
}

/** The lines card: the scan field, the counts and the plan per row. */
export function ReceiveLinesCard({
  registerBeforeSubmit,
  lines,
  emptyHint,
  plans,
  planFetching,
  showPrices,
  taxHandling,
  canWrite,
  focusLineKey,
  shortKeys,
  undatedKeys,
  scanRef,
  onSelectProduct,
  onFocusHandled,
  onUpdate,
  onRemove,
  onQuantityEnter,
  onOpenImport,
  onTogglePrices,
}: Props) {
  const { t } = useTranslation("warehouse");
  const showTax = showPrices && taxHandling !== "NONE";

  return (
    <Card className="overflow-hidden p-0">
      <div className="flex flex-wrap items-center gap-2 border-b border-border px-4 py-3">
        <h2 className="text-base font-semibold text-on">
          {t("receive.linesTitle")}
        </h2>
        <ReceiveScanField
          ref={scanRef}
          disabled={!canWrite}
          onSelect={onSelectProduct}
        />
        <Button
          type="button"
          variant="ghost"
          size="sm"
          leftIcon={<ClipboardPaste size={16} />}
          disabled={!canWrite}
          onClick={onOpenImport}
        >
          {t("receive.pasteRows")}
        </Button>
        <Button
          type="button"
          variant="ghost"
          size="sm"
          aria-pressed={showPrices}
          onClick={onTogglePrices}
        >
          {showPrices ? t("receive.hidePrices") : t("receive.addPrices")}
        </Button>
      </div>

      <div className="relative overflow-x-auto">
        <table className="w-full min-w-[64rem] border-collapse">
          <thead>
            <tr className="text-left text-xs text-on-secondary">
              <th scope="col" className="w-full px-4 py-2 font-medium">
                {t("receive.product")}
              </th>
              <th
                scope="col"
                className="whitespace-nowrap px-2 py-2 font-medium"
              >
                {t("receive.ordered")}
              </th>
              <th scope="col" className="px-2 py-2 font-medium">
                {t("receive.received")}
              </th>
              <th scope="col" className="px-2 py-2 font-medium">
                {t("receive.putOn")}
              </th>
              {showPrices && (
                <th scope="col" className="px-2 py-2 font-medium">
                  {showTax ? t("receive.priceAndVat") : t("receive.unitPrice")}
                </th>
              )}
              <th scope="col" className="w-10 px-2 py-2">
                <span className="sr-only">{t("receive.remove")}</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {lines.length === 0 ? (
              <tr>
                <td
                  colSpan={showPrices ? 6 : 5}
                  className="px-4 py-10 text-center"
                >
                  <p className="text-sm font-medium text-on">
                    {t("receive.emptyTitle")}
                  </p>
                  <p className="mt-1 text-sm text-on-secondary">{emptyHint}</p>
                </td>
              </tr>
            ) : (
              lines.map((line, index) => (
                <ReceiveLineRow
                  key={line.key}
                  line={line}
                  index={index}
                  registerBeforeSubmit={registerBeforeSubmit}
                  plan={plans.get(line.key)}
                  planChecking={planFetching}
                  showPrices={showPrices}
                  showTax={showTax}
                  canWrite={canWrite}
                  focusLineKey={focusLineKey}
                  shortLine={shortKeys.has(line.key)}
                  needsExpiry={undatedKeys.has(line.key)}
                  onFocusHandled={onFocusHandled}
                  onUpdate={onUpdate}
                  onRemove={onRemove}
                  onQuantityEnter={onQuantityEnter}
                />
              ))
            )}
          </tbody>
        </table>
      </div>
    </Card>
  );
}
