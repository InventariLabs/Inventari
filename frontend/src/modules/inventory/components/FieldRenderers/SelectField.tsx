import type { ChangeEvent } from "react";
import type { FieldDefinition } from "@/types";
import { NativeSelect } from "@/components/ui/NativeSelect";
import { getLabel } from "./helpers";

interface SelectFieldProps {
  id: string;
  field: FieldDefinition;
  value: unknown;
  error?: string;
  onChange: (val: string | null) => void;
  /** Resolves the copy for an option and for the "not in the list" marker. */
  tDyn: (key: string, opts?: Record<string, unknown>) => string;
}

/**
 * Renders a `select` field as a picker over the options its definition
 * declares.
 *
 * Until this existed, `select` fell through to the default text input: the
 * definition carried four statuses and the form offered a free-text box, so a
 * value outside the state machine could be typed into a field the state
 * machine guards. The backend has always called this a closed set —
 * `FieldDefinitionCreate` refuses a `select` without a non-empty `options`
 * list (`schemas/category.py`).
 *
 * **The stored value is never dropped on sight.** A `<select>` whose value is
 * absent from its options reports the first option instead, so merely opening
 * a record would change its status on the next save. Two shapes reach us that
 * way and both are real: free text written while this field was an input, and
 * legacy rows whose `options` list is empty (the read schema is lenient about
 * those on purpose). Such a value is offered as its own option, marked, and
 * stays selected — but it is not made saveable: the backend keeps `select` a
 * closed set and refuses a save that carries it, so the record waits for a
 * declared choice rather than letting the value quietly become another one.
 *
 * Clearing is the one edit this control can complete: the empty entry emits
 * `null`, the "not set" sentinel the backend accepts for an optional field.
 * The empty string would not do — `_validate_select` reads it as a value and
 * refuses it with "value '' is not in declared options".
 */
export function SelectField({
  id,
  field,
  value,
  error,
  onChange,
  tDyn,
}: SelectFieldProps) {
  const current = typeof value === "string" ? value : "";
  const options = field.options ?? [];
  const isUnknown = current !== "" && !options.includes(current);

  // An option's word belongs to whoever declared the field: `options_i18n`
  // names a fully-qualified key per option, so the equipment module answers
  // out of its own `equipment:status.*`. Without an entry the option is the
  // user's own word and is rendered exactly as it was typed — the same
  // sentence `getLabel` applies to labels.
  const optionLabel = (opt: string): string => {
    const key = field.options_i18n?.[opt];
    if (!key) return opt;
    return tDyn(key, { defaultValue: opt });
  };

  const handleChange = (e: ChangeEvent<HTMLSelectElement>) =>
    // `""` would be sent as a value and refused by the select validator;
    // `null` is how this form says "not set" and is what survives a save.
    onChange(e.target.value === "" ? null : e.target.value);

  return (
    <NativeSelect
      id={id}
      value={current}
      error={error}
      // Named from the same source as the visible label the parent renders.
      aria-label={getLabel(field, tDyn)}
      aria-required={field.required || undefined}
      onChange={handleChange}
    >
      {/* An optional field has to be clearable, and a required one that is
          still empty must not silently report the first option as a choice
          the reader made. Both need this entry. */}
      <option value="">
        {tDyn("items:fieldOptions.none", { defaultValue: "—" })}
      </option>
      {options.map((opt) => (
        <option key={opt} value={opt}>
          {optionLabel(opt)}
        </option>
      ))}
      {isUnknown && (
        <option value={current}>
          {tDyn("items:fieldOptions.unknownValue", {
            value: current,
            defaultValue: current,
          })}
        </option>
      )}
    </NativeSelect>
  );
}
