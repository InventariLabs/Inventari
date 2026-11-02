import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/Button";
import { QuantityInput } from "@/components/ui/QuantityInput";
import { Sheet, SheetActions, SheetBody } from "@/components/ui/Sheet";
import type { PackingLineOut } from "@/modules/warehouse/api/packing";
import { formatQuantityLocalized } from "@/lib/i18nHelpers";

interface Props {
  line: PackingLineOut;
  /** The package the goods go into; `null` opens a new one. */
  packageCode: string | null;
  isPending: boolean;
  onConfirm: (quantity: number) => void;
  onCancel: () => void;
}

/**
 * How much of a tapped line goes into the package.
 *
 * Prefilled with everything left: the common box takes the whole line, and
 * the field is there for the box that takes part of it.
 */
export function PackLineSheet({
  line,
  packageCode,
  isPending,
  onConfirm,
  onCancel,
}: Props) {
  const { t } = useTranslation("warehouse");
  const left = Number(line.remaining_quantity);
  const [quantity, setQuantity] = useState<number | null>(left);
  const [error, setError] = useState<string | null>(null);

  const confirm = () => {
    if (quantity === null || quantity <= 0) {
      setError(t("packing.qtyRequired"));
      return;
    }
    if (quantity > left) {
      setError(
        t("packing.qtyOver", {
          amount: formatQuantityLocalized(
            t,
            line.remaining_quantity,
            line.uom_symbol,
          ),
        }),
      );
      return;
    }
    onConfirm(quantity);
  };

  return (
    <Sheet
      open
      onClose={onCancel}
      zIndex="modal"
      maxWidth="md"
      aria-labelledby="pack-line-title"
    >
      <SheetBody className="p-5">
        <h3 id="pack-line-title" className="text-base font-semibold text-on">
          {line.product_name ?? t("picking.unknown_product")}
        </h3>
        <p className="mt-1 text-sm text-on-secondary">
          {packageCode
            ? t("packing.intoPackage", { code: packageCode })
            : t("packing.intoNewPackage")}
        </p>
        <div className="mt-4">
          <QuantityInput
            id="pack-line-qty"
            label={t("packing.quantity")}
            description={t("packing.leftToPack", {
              amount: formatQuantityLocalized(
                t,
                line.remaining_quantity,
                line.uom_symbol,
              ),
            })}
            uomSymbol={line.uom_symbol}
            max={left}
            value={quantity ?? ""}
            onQuantityChange={(next) => {
              setQuantity(next);
              setError(null);
            }}
            error={error ?? undefined}
          />
        </div>
        <SheetActions className="mt-5">
          <Button variant="outline" onClick={onCancel} disabled={isPending}>
            {t("picking.back")}
          </Button>
          <Button onClick={confirm} isLoading={isPending}>
            {t("packing.pack")}
          </Button>
        </SheetActions>
      </SheetBody>
    </Sheet>
  );
}
