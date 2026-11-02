import { useTranslation } from "react-i18next";

interface RequiredToggleProps {
  checked: boolean;
  onChange: (checked: boolean) => void;
}

export default function FieldBuilderRequiredToggle({
  checked,
  onChange,
}: RequiredToggleProps) {
  const { t } = useTranslation("common");

  return (
    <label className="flex items-center gap-2 cursor-pointer select-none">
      <div className="relative">
        <input
          type="checkbox"
          checked={checked}
          onChange={(e) => onChange(e.target.checked)}
          className="peer sr-only"
        />
        <div
          className={`h-5 w-9 rounded-full transition-colors ${checked ? "bg-primary-500" : "bg-surface-raised"}`}
        >
          <div
            className={`absolute left-0.5 top-0.5 h-4 w-4 rounded-full bg-white shadow transition-transform ${checked ? "translate-x-4" : ""}`}
          />
        </div>
      </div>
      <span className="text-xs text-on-secondary">{t("labels.required")}</span>
    </label>
  );
}
