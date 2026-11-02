import { useTranslation } from "react-i18next";
import { Input } from "@/components/ui/Input";
import { NativeSelect } from "@/components/ui/NativeSelect";
import { unitLabel } from "@/lib/i18nHelpers";
import { DOCUMENT_HELD_CODES } from "@/modules/warehouse/discrepancyCodes";
import type { ReceiveDraftLine, RowPatch } from "./receiveDraft";

interface Props {
  line: ReceiveDraftLine;
  canWrite: boolean;
  onUpdate: (key: string, patch: RowPatch) => void;
}

/**
 * How much of what arrived is damaged or waiting for a quality decision, and
 * which of the two it is. That quantity goes to quarantine, but the order
 * counts it as delivered; the rest of the count is ordinary stock. Counting 20
 * and holding 2 is one row, not a row of 18 and a row of 2 for the same goods.
 */
export function ReceiveLineHeld({ line, canWrite, onUpdate }: Props) {
  const { t } = useTranslation("warehouse");
  const held = Number(line.heldQuantity);
  const tooMany = held > Number(line.quantity);

  return (
    <div className="flex flex-wrap items-start gap-3">
      <Input
        type="text"
        inputMode="decimal"
        label={t("receive.heldQuantity")}
        aria-label={t("receive.heldQuantityLabel", { product: line.name })}
        description={t("receive.heldHint")}
        aria-invalid={tooMany || undefined}
        value={line.heldQuantity}
        disabled={!canWrite}
        onChange={(event) =>
          onUpdate(line.key, { heldQuantity: event.target.value })
        }
        wrapperClassName="w-40"
        className="text-right tabular-nums"
        suffix={unitLabel(t, line.uomSymbol)}
      />
      <NativeSelect
        label={t("receive.heldWhy")}
        value={line.heldCode}
        disabled={!canWrite}
        onChange={(event) =>
          onUpdate(line.key, {
            heldCode: event.target.value as ReceiveDraftLine["heldCode"],
          })
        }
        wrapperClassName="w-56"
      >
        {DOCUMENT_HELD_CODES.map((code) => (
          <option key={code} value={code}>
            {t(`detail.discrepancyCodes.${code}`)}
          </option>
        ))}
      </NativeSelect>
    </div>
  );
}
