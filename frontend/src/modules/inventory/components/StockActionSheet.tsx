import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import {
  Plus,
  Minus,
  X,
  MapPin,
  Calendar,
  ShoppingCart,
  PackageX,
} from "lucide-react";
import type { LabelScanView } from "@/types";
import { Slot } from "@/components/Slot";
import { Button } from "@/components/ui/Button";
import { Sheet } from "@/components/ui/Sheet";
import { cn } from "@/lib/utils";
import { formatDate, formatDateTime } from "@/utils/helpers";
import { formatQuantityValue } from "@/utils/formatters";
import { unitLabel } from "@/lib/i18nHelpers";
import {
  usePartialPackage,
  usePartlyUsable,
} from "@/modules/shared/hooks/usePartialPackage";
import PartlyUsedSheet, { type LeftAmount } from "./PartlyUsedSheet";
import {
  partialPackageSentence,
  type PartialPackage,
  type PieceMeasure,
} from "@/utils/partialPackage";

interface Props {
  data: LabelScanView;
  onClose: () => void;
  onConsume: (itemId?: string) => void;
  onAddOne: (itemId: string) => void;
  onAdd: () => void;
  onAddToShoppingList?: () => void;
  /** Open a package, or say how much of an open one is left. */
  onUsePartially?: (itemId: string, amount: LeftAmount) => Promise<void>;
  /**
   * Whether to offer the actions that change stock.
   *
   * Defaults to true: the sheet is opened from a scanner, and every caller
   * that can reach one has already asked. A caller that has not keeps the
   * behaviour it had.
   */
  canWrite?: boolean;
}

interface StockItemRowProps {
  item: {
    id: string;
    location: string;
    location_path?: string;
    location_code?: string | null;
    lot?: string | null;
    expiry_date: string | null;
    opened_at?: string | null;
    quantity: number;
    reserved_quantity?: number;
    available_quantity?: number;
  };
  partial: PartialPackage | null;
  canWrite: boolean;
  /** Present when part of this record's package can be used. */
  partlyUse: {
    productName: string;
    measure: PieceMeasure | null;
    packCounted: boolean;
    submit: (amount: LeftAmount) => Promise<void>;
  } | null;
  onConsume: (itemId?: string) => void;
  onAddOne: (itemId: string) => void;
  /** Open the record's own page. */
  onOpen: (itemId: string) => void;
}

/** One record on the shelf: where it stands, what is left of it, and the ± buttons. */
function StockItemRow({
  item,
  partial,
  canWrite,
  partlyUse,
  onConsume,
  onAddOne,
  onOpen,
}: StockItemRowProps) {
  const { t } = useTranslation(["labels", "common", "items"]);
  const [asking, setAsking] = useState(false);
  return (
    <div className="bg-surface-card px-3 py-2.5 rounded-xl border border-border shadow-sm flex flex-wrap items-center justify-between gap-3">
      <div className="min-w-[12rem] flex-1">
        <Button
          type="button"
          variant="ghost"
          size="row"
          onClick={() => onOpen(item.id)}
          className="min-h-11 flex-col items-stretch gap-0 px-0 py-1 font-normal"
        >
          <span className="flex items-start gap-1.5 text-xs font-medium text-on-secondary">
            <MapPin
              size={11}
              className="text-primary-400 flex-shrink-0 mt-0.5"
            />
            <span className="min-w-0 break-words">
              {item.location_path || item.location}
            </span>
            {item.location_code && (
              <span className="font-mono text-on-muted flex-shrink-0">
                {item.location_code}
              </span>
            )}
          </span>
          {item.lot && (
            <span className="block text-xs text-on-muted font-medium mt-0.5">
              {t("stockActions.lotLabel", { lot: item.lot })}
            </span>
          )}
          {item.expiry_date && (
            <span className="block text-xs text-on-muted font-medium mt-0.5">
              {formatDate(item.expiry_date)}
            </span>
          )}
          {item.opened_at && (
            <span className="block text-xs text-on-secondary font-medium mt-0.5">
              {t("items:history.actions.OPENED")}{" "}
              {formatDateTime(item.opened_at)}
            </span>
          )}
          {!!item.reserved_quantity && (
            <span className="block text-xs text-amber-700 font-medium mt-0.5">
              {t("stockActions.reservedAvailable", {
                reserved: formatQuantityValue(item.reserved_quantity),
                available: formatQuantityValue(item.available_quantity ?? 0),
              })}
            </span>
          )}
          {partial && (
            <span className="block text-xs text-on-secondary font-medium mt-0.5">
              {partialPackageSentence(t, partial)}
            </span>
          )}
        </Button>
        {partlyUse && (
          <Button
            type="button"
            variant="link"
            size="inline"
            className="mt-1 text-xs"
            onClick={() => setAsking(true)}
          >
            {t("stockActions.usePartially")}
          </Button>
        )}
        {partlyUse && asking && (
          <PartlyUsedSheet
            itemName={partlyUse.productName}
            measure={partlyUse.measure}
            packCounted={partlyUse.packCounted}
            onSubmit={partlyUse.submit}
            onClose={() => setAsking(false)}
          />
        )}
      </div>
      <div className="ml-auto flex items-center gap-1.5 bg-surface p-1 rounded-lg border border-border">
        {canWrite && (
          <Button
            type="button"
            onClick={() => onConsume(item.id)}
            aria-label={t("stockActions.consume1Title")}
            variant="ghost"
            size="icon"
            className="rounded-md md:h-11 md:w-11 text-on-muted hover:bg-red-50 hover:text-red-500"
          >
            <Minus size={15} />
          </Button>
        )}
        <span className="min-w-[1.75rem] text-center font-semibold text-on text-sm">
          {formatQuantityValue(item.quantity)}
        </span>
        {canWrite && (
          <Button
            type="button"
            onClick={() => onAddOne(item.id)}
            aria-label={t("stockActions.add1Title")}
            variant="ghost"
            size="icon"
            className="rounded-md md:h-11 md:w-11 text-on-muted hover:bg-primary-50 hover:text-primary-600"
          >
            <Plus size={15} />
          </Button>
        )}
      </div>
    </div>
  );
}

/** What is left in the shelf's total when it is a fraction of a piece. */
function TotalPartialNote({ pack }: { pack: PartialPackage | null }) {
  const { t } = useTranslation(["labels", "common"]);
  if (!pack) return null;
  return (
    <p className="-mt-2 mb-3 text-right text-xs font-medium text-on-secondary">
      {partialPackageSentence(t, pack)}
    </p>
  );
}

export default function StockActionSheet({
  data,
  onClose,
  onConsume,
  onAddOne,
  onAdd,
  onAddToShoppingList,
  onUsePartially,
  canWrite = true,
}: Props) {
  const { t } = useTranslation(["labels", "common"]);
  const navigate = useNavigate();
  const partialOf = usePartialPackage();
  const partlyUsableOf = usePartlyUsable();

  if (!data.stock_summary) return null;

  const { unit, items, template } = data.stock_summary;
  const partlyUsable =
    canWrite && onUsePartially ? partlyUsableOf(template) : null;
  const partlyUseFor = (itemId: string) =>
    partlyUsable && onUsePartially
      ? {
          productName: template?.name ?? "",
          measure: partlyUsable.measure,
          packCounted: partlyUsable.packCounted,
          submit: (amount: LeftAmount) => onUsePartially(itemId, amount),
        }
      : null;
  // The scan carries the card's per-piece weight or volume, so a partly used
  // package can say what is left in kilograms instead of as 0.75 pcs.
  const partialFor = (quantity: number) =>
    partialOf({ quantity, uomId: template?.uom_id, template });

  // Filter out virtual/consumed locations — only show real stock
  const realItems = (items ?? []).filter(
    (it) => !it.location.toLowerCase().includes("virtual") && it.quantity > 0,
  );
  const realTotal = realItems.reduce((acc, it) => acc + it.quantity, 0);
  const isEmpty = realTotal === 0;
  const totalPartial = partialFor(realTotal);

  // Earliest expiry among real items
  const nextExpiringItem = [...realItems].sort((a, b) => {
    if (!a.expiry_date) return 1;
    if (!b.expiry_date) return -1;
    return (
      new Date(a.expiry_date).getTime() - new Date(b.expiry_date).getTime()
    );
  })[0];

  const openRecord = (itemId: string) => {
    navigate(`/inventory/items/${encodeURIComponent(itemId)}`);
    onClose();
  };

  // The sheet's name in one place: the template's own name when the scan
  // matched a product, otherwise the value the server sent with its key (the
  // line under the scan's status is a catalogue key now, not a sentence).
  const heading =
    data.stock_summary.template?.name ?? data.message_params?.product ?? "";

  return (
    <Sheet open onClose={onClose} backdropOpacity={60} aria-label={heading}>
      <div className="w-12 h-1.5 bg-surface-inset rounded-full mx-auto mt-3 mb-1 sm:hidden" />

      <div className="p-6 flex-1 overflow-y-auto">
        {/* Header */}
        <div className="flex justify-between items-start mb-5">
          <div className="flex items-start gap-3 flex-1 min-w-0 pr-3">
            {data.stock_summary.template?.image_url && (
              <img
                src={data.stock_summary.template.image_url}
                alt={data.stock_summary.template?.name ?? ""}
                loading="lazy"
                className="w-14 h-14 rounded-xl object-cover shrink-0 border border-border bg-surface-raised"
                onError={(e) => {
                  (e.currentTarget as HTMLImageElement).style.display = "none";
                }}
              />
            )}
            <div className="min-w-0">
              <h3 className="font-semibold text-xl text-on leading-tight">
                {heading}
              </h3>
              {data.stock_summary.template?.brand && (
                <span className="inline-block text-[10px] font-medium text-on-secondary uppercase tracking-tight bg-surface-raised px-1.5 py-0.5 rounded mt-1">
                  {data.stock_summary.template.brand}
                </span>
              )}
              <p className="text-on-muted text-xs mt-1 font-mono">
                {data.label_code}
              </p>
            </div>
          </div>
          <Button
            variant="ghost"
            onClick={onClose}
            aria-label={t("common:a11y.close")}
            className="rounded-full shrink-0"
          >
            <X size={22} />
          </Button>
        </div>

        {isEmpty ? (
          /* ── EMPTY STATE ── */
          <div className="flex flex-col items-center text-center py-4 mb-5">
            <div className="w-16 h-16 bg-surface-raised rounded-2xl flex items-center justify-center mb-3">
              <PackageX size={28} className="text-on-muted" />
            </div>
            <p className="font-semibold text-on-secondary text-base mb-1">
              {t("stockActions.outOfStock")}
            </p>
            <p className="text-sm text-on-muted">{t("stockActions.allUsed")}</p>
          </div>
        ) : (
          /* ── STOCK SUMMARY ── */
          <div className="bg-surface rounded-2xl p-4 mb-5 border border-border">
            <div className="flex justify-between items-center mb-3">
              <span className="text-xs font-medium text-on-muted uppercase tracking-widest">
                {t("stockActions.inStock")}
              </span>
              <span className="text-2xl font-semibold text-primary-600">
                {realTotal}{" "}
                <span className="text-sm font-medium text-on-muted">
                  {unitLabel(t, unit, realTotal)}
                </span>
              </span>
            </div>
            <TotalPartialNote pack={totalPartial} />

            {nextExpiringItem?.expiry_date && (
              <div className="flex items-center gap-2 text-[10px] text-amber-700 bg-amber-50 px-2 py-1 rounded-lg border border-amber-100 w-fit mb-3">
                <Calendar size={12} />
                <span className="font-medium uppercase tracking-tight">
                  {t("stockActions.firstExpiry", {
                    date: formatDate(nextExpiringItem.expiry_date),
                  })}
                </span>
              </div>
            )}

            <div className="space-y-2 max-h-[40vh] overflow-y-auto pr-1">
              {realItems.map((item) => (
                <StockItemRow
                  key={item.id}
                  item={item}
                  partial={partialFor(item.quantity)}
                  canWrite={canWrite}
                  partlyUse={partlyUseFor(item.id)}
                  onConsume={onConsume}
                  onAddOne={onAddOne}
                  onOpen={openRecord}
                />
              ))}
            </div>
          </div>
        )}

        {/* Modular Slot */}
        <Slot
          name="stock_action_extra"
          data={{
            barcode: data.label_code,
            template: data.stock_summary.template,
          }}
          className="mb-4"
        />

        {/* ── ACTION BUTTONS ── */}
        <div className="space-y-2.5">
          {!isEmpty && canWrite && (
            <Button
              onClick={() => onConsume()}
              variant="primary"
              size="lg"
              className="w-full rounded-2xl font-semibold"
              leftIcon={<Minus size={20} />}
            >
              {t("stockActions.consume")}
            </Button>
          )}

          {canWrite && (
            <Button
              onClick={onAdd}
              variant={isEmpty ? "primary" : "outline"}
              size="lg"
              className={cn(
                "w-full rounded-2xl font-semibold border",
                isEmpty
                  ? ""
                  : "bg-surface-card text-on-secondary hover:border-primary-300 hover:text-primary-700",
              )}
              leftIcon={<Plus size={18} />}
            >
              {t("stockActions.addToWarehouse")}
            </Button>
          )}

          {onAddToShoppingList && (
            <Button
              onClick={onAddToShoppingList}
              variant="outline"
              size="lg"
              className="w-full rounded-2xl font-semibold border bg-surface-card text-on-secondary hover:border-primary-300 hover:text-primary-700"
              leftIcon={<ShoppingCart size={16} />}
            >
              {t("stockActions.addToShoppingList")}
            </Button>
          )}

          <Button
            onClick={() => {
              if (realItems.length === 1) {
                openRecord(realItems[0].id);
                return;
              }
              navigate(`/inventory/items?search=${data.label_code}`);
              onClose();
            }}
            variant="ghost"
            className="w-full py-2 text-xs font-medium uppercase tracking-widest text-on-muted"
          >
            {t("stockActions.viewDetails")}
          </Button>
        </div>
      </div>
    </Sheet>
  );
}
