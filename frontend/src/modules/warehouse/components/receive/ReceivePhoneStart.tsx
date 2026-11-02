import { lazy, Suspense, useState, type RefObject } from "react";
import { useTranslation } from "react-i18next";
import { Camera, ScanLine, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import type { ProductSearchResult } from "@/modules/warehouse/api/documents";
import { LineQuantityStepper } from "@/modules/warehouse/components/LineQuantityStepper";
import { ReceiveScanField } from "./ReceiveScanField";
import {
  lineForProduct,
  type ReceiveDraftLine,
  type RowPatch,
} from "./receiveDraft";

/** The phone's one door into the receiving session. */
export interface PhoneDoor {
  canWrite: boolean;
  starting: boolean;
  onStart: () => void;
}

/** The goods on the sheet: the order's rows, and what came beside them. */
export interface PhoneGoods {
  lines: ReceiveDraftLine[];
  scanRef: RefObject<HTMLInputElement>;
  onSelect: (product: ProductSearchResult) => void;
  onUpdate: (key: string, patch: RowPatch) => void;
  onRemove: (key: string) => void;
}

interface Props {
  door: PhoneDoor;
  /** A waiting order is chosen: the delivery has lines to walk. */
  hasOrder: boolean;
  ordersLoading: boolean;
  goods: PhoneGoods;
  /** What stops the start: a missing field, or the save the server refused. */
  error: string | null;
}

/** The camera's own chunk, fetched the first time the worker opens it. */
const ReceiveCamera = lazy(() => import("./ReceiveCamera"));

/** The camera beside the scan field, opened and closed by one button. */
function CameraScan({
  disabled,
  onSelect,
}: {
  disabled: boolean;
  onSelect: (product: ProductSearchResult) => void;
}) {
  const { t } = useTranslation("warehouse");
  const [open, setOpen] = useState(false);

  return (
    <>
      <Button
        type="button"
        variant="outline"
        size="lg"
        className="w-full"
        leftIcon={<Camera size={16} />}
        aria-pressed={open}
        disabled={disabled}
        onClick={() => setOpen(!open)}
      >
        {open ? t("scan.close") : t("scan.open")}
      </Button>
      {open && (
        <Suspense fallback={null}>
          <ReceiveCamera onSelect={onSelect} onClose={() => setOpen(false)} />
        </Suspense>
      )}
    </>
  );
}

/**
 * What arrived that no order lists: scanned in, each with how many came.
 *
 * The order's own rows are counted on the session and are not listed here;
 * a product one of them already carries is named as such rather than added
 * a second time, which the session would then expect twice.
 */
function PhoneGoodsEntry({
  goods,
  intro,
  disabled,
}: {
  goods: PhoneGoods;
  intro: string;
  disabled: boolean;
}) {
  const { t } = useTranslation("warehouse");
  const [onOrder, setOnOrder] = useState<string | null>(null);
  const extra = goods.lines.filter((line) => line.sourcePoLineId === null);
  const select = (product: ProductSearchResult) => {
    const ordered = goods.lines.filter((line) => line.sourcePoLineId !== null);
    const row = lineForProduct(ordered, product);
    setOnOrder(row ? row.name : null);
    if (!row) goods.onSelect(product);
  };
  return (
    <>
      <p className="text-sm text-on-secondary">{intro}</p>
      <ReceiveScanField
        ref={goods.scanRef}
        disabled={disabled}
        onSelect={select}
      />
      <CameraScan disabled={disabled} onSelect={select} />
      {onOrder && (
        <p role="status" className="text-sm text-on-secondary">
          {t("receive.phone.onOrder", { product: onOrder })}
        </p>
      )}
      {extra.length > 0 && (
        <ul className="divide-y divide-border">
          {extra.map((line) => (
            <li key={line.key} className="space-y-2 py-3">
              <div className="flex items-center justify-between gap-3">
                <p className="min-w-0 truncate text-sm font-medium text-on">
                  {line.name}
                </p>
                <Button
                  type="button"
                  variant="ghostDanger"
                  size="icon"
                  aria-label={t("receive.removeLine", { product: line.name })}
                  title={t("receive.removeLine", { product: line.name })}
                  disabled={disabled}
                  onClick={() => goods.onRemove(line.key)}
                >
                  <Trash2 size={16} aria-hidden="true" />
                </Button>
              </div>
              <LineQuantityStepper
                value={Number(line.quantity) || 0}
                min={0}
                uomId={line.uomId}
                label={t("receive.quantityLabel", { product: line.name })}
                onChange={(next) =>
                  goods.onUpdate(line.key, { quantity: String(next ?? 0) })
                }
              />
            </li>
          ))}
        </ul>
      )}
    </>
  );
}

/**
 * The phone's door into receiving: the delivery is chosen above, and the
 * goods are then counted one at a time on the session a receipt document
 * opens — the camera, the count and the suggested location live there, and
 * a phone has one way of receiving rather than a second, smaller sheet.
 *
 * A waiting order already lists the goods. For goods nobody ordered — the
 * whole delivery, or what a supplier brought beside its order — the phone
 * first takes in what arrived, scanned, with how many, since the session
 * walks the receipt's lines and cannot name a product of its own; the same
 * door then opens the session on them.
 */
export function ReceivePhoneStart({
  door,
  hasOrder,
  ordersLoading,
  goods,
  error,
}: Props) {
  const { t } = useTranslation("warehouse");

  if (!hasOrder && ordersLoading) return null;

  return (
    <Card className="space-y-3 p-4">
      {hasOrder && (
        <p className="text-sm text-on-secondary">{t("receive.phone.hint")}</p>
      )}
      <PhoneGoodsEntry
        goods={goods}
        intro={hasOrder ? t("receive.phone.extra") : t("receive.phone.noOrder")}
        disabled={!door.canWrite}
      />
      {error && (
        <p role="alert" className="text-sm text-on-danger">
          {error}
        </p>
      )}
      <Button
        type="button"
        size="lg"
        className="w-full"
        leftIcon={<ScanLine size={18} />}
        disabled={!door.canWrite || door.starting}
        isLoading={door.starting}
        onClick={door.onStart}
      >
        {door.starting ? t("receive.phone.starting") : t("receive.phone.start")}
      </Button>
    </Card>
  );
}
