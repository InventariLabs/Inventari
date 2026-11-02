import type { ChangeEvent } from "react";
import { useTranslation } from "react-i18next";
import type { FieldDefinition } from "@/types";
import { makeTDynamic } from "@/lib/i18nHelpers";

interface MultiSelectFieldProps {
  field: FieldDefinition;
  value: unknown;
  error?: string;
  onChange: (val: string[]) => void;
}

function toStringArray(raw: unknown): string[] {
  if (Array.isArray(raw)) {
    return raw.filter((v): v is string => typeof v === "string");
  }
  return [];
}

/**
 * Renders a `multi-select` field as a row of checkboxes.
 *
 * The component is controlled — each toggle emits a fresh sorted string
 * array so the parent can persist it as ``meta_data[key]``.
 *
 * The words come from the declaration, same as `SelectField`: an option
 * named in `options_i18n` is rendered through its fully-qualified key (the
 * declaring module's own `equipment:status.*`, say), and an option with no
 * entry is the user's own word, rendered verbatim.
 */
export function MultiSelectField({
  field,
  value,
  error,
  onChange,
}: MultiSelectFieldProps) {
  const { t } = useTranslation("items");
  const tDyn = makeTDynamic(t);
  const selected = new Set(toStringArray(value));
  const options = field.options ?? [];

  const optionLabel = (opt: string): string => {
    const key = field.options_i18n?.[opt];
    if (!key) return opt;
    return tDyn(key, { defaultValue: opt });
  };

  const toggle = (opt: string) => {
    if (selected.has(opt)) {
      selected.delete(opt);
    } else {
      selected.add(opt);
    }
    onChange([...selected].sort());
  };

  const handleChange = (opt: string) => (_e: ChangeEvent<HTMLInputElement>) =>
    toggle(opt);

  return (
    <div
      className={`flex flex-wrap gap-2 ${error ? "p-2 border border-red-300 bg-red-50 rounded-lg" : ""}`}
    >
      {options.map((opt) => (
        <label
          key={opt}
          className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-border bg-surface-card cursor-pointer hover:bg-surface text-sm"
        >
          <input
            type="checkbox"
            checked={selected.has(opt)}
            onChange={handleChange(opt)}
            className="rounded border-border"
          />
          <span className="text-on-secondary">{optionLabel(opt)}</span>
        </label>
      ))}
      {options.length === 0 && (
        <p className="text-xs text-on-muted">
          {t("fieldOptions.noneConfigured")}
        </p>
      )}
    </div>
  );
}
