import { useTranslation } from "react-i18next";
import { NativeSelect } from "@/components/ui/NativeSelect";
import { useOrganization } from "@/modules/settings/hooks/useOrganization";

/**
 * The preset identifiers the backend stores, and the key each is named by.
 *
 * The list read "Simple, PL Magazyn, UK Warehouse, DE Lager, Full Value" in
 * every language: country codes, some of them spelled in the local language, and two
 * configuration states, none of it translated. The identifier stays on the
 * wire; the screen shows a name.
 */
const PRESET_KEYS: Record<string, string> = {
  Simple: "simple",
  "PL Magazyn": "pl_warehouse",
  "UK Warehouse": "uk_warehouse",
  "DE Lager": "de_warehouse",
  "FR Entrepôt": "fr_warehouse",
  "ES Almacén": "es_warehouse",
  "Full Value": "full_value",
};

/**
 * The country each regional preset belongs to. The organization's country
 * decides the tax rule on its own; this only picks which preset is offered
 * first, so a Polish organization is not left to find "PL Magazyn" in a list.
 */
const PRESET_COUNTRY: Record<string, string> = {
  "PL Magazyn": "PL",
  "UK Warehouse": "GB",
  "DE Lager": "DE",
  "FR Entrepôt": "FR",
  "ES Almacén": "ES",
};

interface ProfilePresetSelectorProps {
  selectedPreset: string;
  presets: string[];
  isPending: boolean;
  onChange: (preset: string) => void;
  onApply: (preset: string) => void;
}

export function ProfilePresetSelector({
  selectedPreset,
  presets,
  isPending,
  onChange,
  onApply,
}: ProfilePresetSelectorProps) {
  const { t } = useTranslation("warehouse");
  const { data: organization } = useOrganization();
  const country = organization?.country;
  const suggested = country
    ? presets.find((preset) => PRESET_COUNTRY[preset] === country)
    : undefined;
  const ordered = suggested
    ? [suggested, ...presets.filter((preset) => preset !== suggested)]
    : presets;

  return (
    <div className="max-w-md">
      <NativeSelect
        // The section heading above it is not a label: the control itself had
        // no accessible name, only an em-dashed placeholder option.
        aria-label={t("profile.presetsLabel")}
        value={selectedPreset}
        onChange={(e) => {
          const val = e.target.value;
          onChange(val);
          if (val) onApply(val);
        }}
        disabled={isPending}
      >
        <option value="">— {t("profile.presetsLabel")} —</option>
        {ordered.map((preset) => {
          const name = PRESET_KEYS[preset]
            ? t(`profile.presets.${PRESET_KEYS[preset]}`)
            : preset;
          return (
            <option key={preset} value={preset}>
              {preset === suggested
                ? t("profile.presetSuggested", { name })
                : name}
            </option>
          );
        })}
      </NativeSelect>
      {isPending && (
        <p className="text-[10px] text-primary-600 font-medium mt-1.5 animate-pulse">
          {t("profile.applyPreset")}...
        </p>
      )}
    </div>
  );
}
