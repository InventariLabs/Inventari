import { useId } from "react";
import { useTranslation } from "react-i18next";
import { Input } from "@/components/ui/Input";
import { ScanToFill } from "@/module-sdk";
import { useCarrierSuggestions } from "@/modules/warehouse/hooks/useCarrierSuggestions";
import type { ShipmentDraft } from "./shipmentDraft";

interface Props {
  value: ShipmentDraft;
  onChange: (draft: ShipmentDraft) => void;
  /** Shown on the carrier field — the one a tracking number needs. */
  error?: string;
}

/**
 * The carrier and tracking number a dispatch is completed with — both
 * optional, so completing without them is the completion it always was.
 *
 * The carrier is free text with the organization's own carriers offered as
 * it is typed: a list to pick from could not take the first parcel sent with
 * a new courier, and the browser's own suggestion list works on a phone.
 *
 * The tracking number arrives printed, as a barcode on the carrier's parcel
 * label, so the camera can read it into its field; the field stays typed
 * and editable either way.
 */
export function ShipmentFields({ value, onChange, error }: Props) {
  const { t } = useTranslation("warehouse");
  // A failed read leaves the field as free text, and says why nothing is
  // offered instead of passing for an organization with no carriers yet.
  const { data: carriers = [], isError } = useCarrierSuggestions();
  const listId = `${useId()}-carriers`;
  return (
    <fieldset className="space-y-3">
      <legend className="text-sm font-semibold text-on">
        {t("shipping.title")}
      </legend>
      <p className="text-xs text-on-secondary">{t("shipping.hint")}</p>
      {/* Tops, not bottoms: the carrier field can grow a message underneath,
          which would lift its control above its neighbour's; both labels are
          one short line in every language. */}
      <div className="grid grid-cols-1 items-start gap-3 sm:grid-cols-2">
        <Input
          label={t("shipping.carrier")}
          list={listId}
          autoComplete="off"
          maxLength={100}
          value={value.carrier}
          error={error}
          description={isError ? t("shipping.suggestionsFailed") : undefined}
          onChange={(e) => onChange({ ...value, carrier: e.target.value })}
        />
        <Input
          label={t("shipping.trackingNumber")}
          autoComplete="off"
          maxLength={100}
          value={value.trackingNumber}
          onChange={(e) =>
            onChange({ ...value, trackingNumber: e.target.value })
          }
        />
      </div>
      <ScanToFill
        pinned
        label={t("shipping.scanTracking")}
        onCode={(code) =>
          onChange({ ...value, trackingNumber: code.slice(0, 100) })
        }
      />
      <datalist id={listId}>
        {carriers.map((carrier) => (
          <option key={carrier} value={carrier} />
        ))}
      </datalist>
    </fieldset>
  );
}
