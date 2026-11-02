import { useTranslation } from "react-i18next";
import { NativeSelect } from "@/components/ui/NativeSelect";
import { Input } from "@/components/ui/Input";
import { Checkbox } from "@/components/ui/Checkbox";
import { CURRENCY_CODES, currencyLabel } from "@/lib/currencies";
import type { TaxHandling } from "@/modules/warehouse/types";

interface ValueTrackingSettingsProps {
  valueTracking: boolean;
  taxHandling: TaxHandling;
  defaultTaxRate: string;
  defaultCurrency: string;
  onValueTrackingChange: (enabled: boolean) => void;
  onTaxHandlingChange: (handling: TaxHandling) => void;
  onDefaultTaxRateChange: (rate: string) => void;
  onDefaultCurrencyChange: (currency: string) => void;
}

export function ValueTrackingSettings({
  valueTracking,
  taxHandling,
  defaultTaxRate,
  defaultCurrency,
  onValueTrackingChange,
  onTaxHandlingChange,
  onDefaultTaxRateChange,
  onDefaultCurrencyChange,
}: ValueTrackingSettingsProps) {
  const { t, i18n } = useTranslation("warehouse");

  return (
    <div className="space-y-6">
      <Checkbox
        checked={valueTracking}
        onChange={(e) => {
          onValueTrackingChange(e.target.checked);
          if (!e.target.checked) onTaxHandlingChange("NONE");
        }}
        className="h-4 w-4 cursor-pointer"
        label={
          <span className="text-sm font-medium text-on">
            {t("profile.enableValueTracking")}
          </span>
        }
      />

      {valueTracking && (
        <div className="grid grid-cols-1 md:grid-cols-2 items-end gap-4 animate-in slide-in-from-top-2 duration-200">
          <NativeSelect
            label={t("profile.taxHandling")}
            value={taxHandling}
            onChange={(e) => onTaxHandlingChange(e.target.value as TaxHandling)}
          >
            <option value="NONE">{t("profile.taxHandlingNone")}</option>
            <option value="SIMPLE_RATE">
              {t("profile.taxHandlingSimplex")}
            </option>
            <option value="PER_LINE_RATE">
              {t("profile.taxHandlingPerLine")}
            </option>
          </NativeSelect>

          {taxHandling !== "NONE" && (
            <Input
              type="number"
              min={0}
              max={100}
              step={0.01}
              label={t("profile.defaultTaxRate")}
              value={defaultTaxRate}
              onChange={(e) => onDefaultTaxRateChange(e.target.value)}
              rightIcon={<span className="text-xs font-medium">%</span>}
            />
          )}

          <NativeSelect
            label={t("profile.defaultCurrency")}
            value={defaultCurrency}
            onChange={(e) => onDefaultCurrencyChange(e.target.value)}
          >
            <option value="">—</option>
            {CURRENCY_CODES.map((code) => (
              <option key={code} value={code}>
                {code} — {currencyLabel(code, i18n.language)}
              </option>
            ))}
          </NativeSelect>
        </div>
      )}
    </div>
  );
}
