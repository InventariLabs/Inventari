import { useTranslation } from "react-i18next";
import type { FieldDefinition } from "@/types";

interface BooleanFieldProps {
  /** Id the surrounding label points at. */
  id?: string;
  field: FieldDefinition;
  value: unknown;
  error?: string;
  onChange: (val: boolean) => void;
}

function toBool(raw: unknown): boolean {
  if (typeof raw === "boolean") return raw;
  if (typeof raw === "string") return raw === "true" || raw === "1";
  if (typeof raw === "number") return raw !== 0;
  return false;
}

/**
 * Renders a `boolean` field as a single checkbox. The component is
 * controlled — every toggle emits the resolved boolean.
 */
export function BooleanField({
  id,
  value,
  error,
  onChange,
}: BooleanFieldProps) {
  const { t } = useTranslation("items");
  const checked = toBool(value);
  return (
    <label
      className={`inline-flex items-center gap-2 cursor-pointer ${
        error ? "p-2 border border-red-300 bg-red-50 rounded-lg" : ""
      }`}
    >
      <input
        id={id}
        type="checkbox"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
        className="rounded border-border"
      />
      <span className="text-sm text-on-secondary">{t("fieldOptions.yes")}</span>
    </label>
  );
}
