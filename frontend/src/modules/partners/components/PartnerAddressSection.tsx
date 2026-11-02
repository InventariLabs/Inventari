import { useMemo } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { NativeSelect } from "@/components/ui/NativeSelect";
import { COUNTRY_CODES, countryLabel, isCountryCode } from "@/lib/countries";
import type { PartnerAddress } from "@/types";

interface PartnerAddressSectionProps {
  address: PartnerAddress | null | undefined;
  open: boolean;
  onToggle: () => void;
  onChange: (field: keyof PartnerAddress, value: string) => void;
}

/** The collapsible address block of the partner form. */
export function PartnerAddressSection({
  address,
  open,
  onToggle,
  onChange,
}: PartnerAddressSectionProps) {
  const { t, i18n } = useTranslation(["partners", "common"]);
  const countryNames = useMemo(() => {
    const locale = i18n.language || "en";
    const names = new Map<string, string>();
    for (const code of COUNTRY_CODES) {
      names.set(code, countryLabel(code, locale));
    }
    return names;
  }, [i18n.language]);

  return (
    <div className="border border-border rounded-lg overflow-hidden">
      <Button
        size="content"
        type="button"
        variant="ghost"
        className="w-full justify-between px-3 py-2.5 text-sm text-on-secondary hover:bg-surface-hover transition-colors"
        onClick={onToggle}
      >
        <span className="text-xs font-medium uppercase tracking-wide">
          {t("address.section")}
        </span>
        {open ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
      </Button>

      {open && (
        <div className="p-3 space-y-3 border-t border-border">
          <Input
            label={t("address.street")}
            value={address?.street ?? ""}
            onChange={(e) => onChange("street", e.target.value)}
            placeholder={t("form.street_placeholder")}
          />
          <div className="grid grid-cols-2 items-end gap-3">
            <Input
              label={t("address.postalCode")}
              value={address?.postal_code ?? ""}
              onChange={(e) => onChange("postal_code", e.target.value)}
              placeholder={t("form.postal_placeholder")}
            />
            <Input
              label={t("address.city")}
              value={address?.city ?? ""}
              onChange={(e) => onChange("city", e.target.value)}
              placeholder={t("form.city_placeholder")}
            />
          </div>
          <NativeSelect
            label={t("address.country")}
            value={address?.country ?? ""}
            onChange={(e) => onChange("country", e.target.value)}
          >
            <option value="">{t("address.countrySelect")}</option>
            {!isCountryCode(address?.country) && address?.country ? (
              <option value={address.country}>
                {t("address.otherCountry", { value: address.country })}
              </option>
            ) : null}
            {COUNTRY_CODES.map((code) => (
              <option key={code} value={code}>
                {countryNames.get(code) ?? code}
              </option>
            ))}
          </NativeSelect>
        </div>
      )}
    </div>
  );
}
