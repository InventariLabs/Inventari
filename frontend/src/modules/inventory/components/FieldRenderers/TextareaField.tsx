import { useTranslation } from "react-i18next";
import { Textarea } from "@/components/ui/Textarea";
import { makeTDynamic } from "@/lib/i18nHelpers";
import { cn } from "@/lib/utils";
import type { FieldDefinition } from "@/types";
import { getPlaceholder, getLabel } from "./helpers";

interface TextareaFieldProps {
  /** Id the surrounding label points at. */
  id?: string;
  field: FieldDefinition;
  value: unknown;
  commonClasses: string;
  error?: string;
  onChange: (value: unknown) => void;
}

export function TextareaField({
  id,
  field,
  value,
  commonClasses,
  error: _error,
  onChange,
}: TextareaFieldProps) {
  const { t } = useTranslation(["items"]);
  const tDyn = makeTDynamic(t);
  const stringVal = String(value ?? "");

  return (
    <Textarea
      id={id}
      value={stringVal}
      onChange={(e) => onChange(e.target.value)}
      // Named from the same source as the visible label the parent renders.
      aria-label={getLabel(field, tDyn)}
      placeholder={getPlaceholder(field, undefined, tDyn)}
      className={cn(commonClasses, "min-h-[80px] resize-none")}
      rows={3}
    />
  );
}
