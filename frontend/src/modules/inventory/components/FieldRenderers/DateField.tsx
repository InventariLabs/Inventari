import { DateInput, type DatePresetId } from "@/components/ui/DateInput";
import type { FieldDefinition } from "@/types";

interface DateFieldProps {
  /** Id the surrounding label points at — lands on the picker's trigger. */
  id?: string;
  field: FieldDefinition;
  value: unknown;
  error?: string;
  onChange: (value: unknown) => void;
}

/** Thin adapter: the shared date field, with the presets this field asks for. */
export function DateField({
  id,
  field,
  value,
  error,
  onChange,
}: DateFieldProps) {
  return (
    <DateInput
      id={id}
      value={String(value ?? "")}
      onChange={onChange}
      error={error}
      presets={(field.date_presets as DatePresetId[]) ?? []}
    />
  );
}
