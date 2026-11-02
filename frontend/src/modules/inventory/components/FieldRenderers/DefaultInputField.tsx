import { MapPin, Info } from "lucide-react";
import { makeTDynamic } from "@/lib/i18nHelpers";
import { useTranslation } from "react-i18next";
import { cn } from "@/lib/utils";
import { Input } from "@/components/ui/Input";
import { formatQuantityLocale } from "@/utils/formatters";
import type { FieldDefinition, UomCategory, Uom } from "@/types";
import { getPlaceholder, getLabel } from "./helpers";

interface DefaultInputFieldProps {
  /** Id the surrounding label points at. */
  id?: string;
  field: FieldDefinition;
  value: unknown;
  quantity?: unknown;
  uomId?: string;
  uomCategories?: UomCategory[];
  error?: string;
  onChange: (value: unknown) => void;
}

/**
 * Default field renderer for text and number inputs
 * Includes special handling for shelf_location (icon), weight (suffix), and hints
 */
export function DefaultInputField({
  id,
  field,
  value,
  quantity,
  uomId,
  uomCategories,
  onChange,
}: DefaultInputFieldProps) {
  const { t } = useTranslation(["items"]);
  const tDyn = makeTDynamic(t);
  const stringVal = String(value ?? "");

  // The unit comes from the UoM catalogue, never from a symbol carried in
  // form state — that second source is gone.
  const uomCategory = uomCategories?.find((c) =>
    c.uoms?.some((u: Uom) => u.id === uomId),
  );
  const unit = uomCategory?.uoms?.find((u: Uom) => u.id === uomId)?.symbol;
  const isVol = uomCategory?.name === "Volume";

  return (
    <div>
      <div className="relative flex items-center">
        {/* Optional Icon for specific fields */}
        {field.key === "shelf_location" && (
          <MapPin className="absolute left-4 z-10 text-on-muted" size={18} />
        )}

        <Input
          id={id}
          type={field.type === "number" ? "number" : "text"}
          inputMode={field.type === "number" ? "decimal" : "text"}
          step={field.type === "number" ? "any" : undefined}
          value={stringVal}
          // The visible label is rendered by UnifiedFieldRenderer, a file
          // boundary away, so the name is carried here from the same source
          // (`getLabel`) rather than left to the id/htmlFor pairing alone.
          aria-label={getLabel(field, tDyn)}
          onChange={(e) => {
            let val: string | null = e.target.value;
            if (field.type === "number") {
              if (val === "") {
                val = null;
              } else {
                val = val.replace(",", ".");
              }
            }
            onChange(val);
          }}
          placeholder={getPlaceholder(field, unit, tDyn)}
          className={cn(
            field.key === "shelf_location" ? "pl-11" : "",
            field.key === "weight" ? "pr-12" : "",
          )}
        />

        {/* Suffix for Weight field */}
        {field.key === "weight" && (
          <div className="absolute right-4 z-10 text-xs font-medium text-on-muted uppercase pointer-events-none bg-surface-card pl-2">
            {t(`common:units.${isVol ? "ml" : "g"}`, {
              defaultValue: isVol ? "ml" : "g",
            })}
          </div>
        )}
      </div>

      {/* Hints */}
      {field.key === "quantity" && (
        <p className="text-xs text-on-muted mt-1.5 flex items-center gap-1.5 font-medium animate-in slide-in-from-top-1">
          <Info size={12} className="text-primary-400" />
          {unit
            ? tDyn(`items:quantityHints.${unit}`, { defaultValue: "" })
            : null}
        </p>
      )}

      {field.key === "weight" &&
        !["kg", "g", "l", "ml"].includes(unit || "") && (
          <>
            <p className="text-xs text-on-muted mt-1 flex items-center gap-1.5 font-medium animate-in slide-in-from-top-1">
              <Info size={12} className="text-primary-400" />
              {t("items:weightPerPieceHint", {
                defaultValue:
                  "Enter the weight of one piece; the total will be calculated automatically.",
              })}
            </p>
            {quantity &&
              value &&
              (() => {
                const qty = parseFloat(String(quantity));
                const perPiece = parseFloat(String(value));
                if (isNaN(qty) || qty <= 0 || isNaN(perPiece)) return null;
                const totalGrams = perPiece * qty;
                const totalKg = totalGrams / 1000;
                return (
                  <p className="text-xs text-on-muted mt-0.5 flex items-center gap-1.5 font-medium animate-in slide-in-from-top-1">
                    {/* Both figures are computed here, so they take the
                        interface language's mark, not the browser's. */}
                    <Info size={12} className="text-primary-400" />≈{" "}
                    {formatQuantityLocale(String(totalGrams), 0)} g (
                    {formatQuantityLocale(String(totalKg), 2)} kg){" "}
                    {t("items:totalWeight")}
                  </p>
                );
              })()}
          </>
        )}
    </div>
  );
}
