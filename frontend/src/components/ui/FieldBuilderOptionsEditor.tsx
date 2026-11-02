import { Input } from "@/components/ui/Input";
import { X } from "lucide-react";
import { useTranslation } from "react-i18next";

interface FieldBuilderOptionsEditorProps {
  value: string[];
  onChange: (options: string[]) => void;
  /** The text in the box, owned by the form: a form that is saved with text
   *  typed and not confirmed can settle it instead of dropping it. */
  input: string;
  onInputChange: (input: string) => void;
}

/**
 * Tag-style options editor for `select` / `multi-select` custom fields.
 *
 * Backend (`FieldDefinitionCreate`) requires a non-empty `options` list for
 * these types, so the parent form must block submission when the list is empty.
 */
export default function FieldBuilderOptionsEditor({
  value,
  onChange,
  input,
  onInputChange: setInput,
}: FieldBuilderOptionsEditorProps) {
  const { t } = useTranslation(["common", "modules"]);

  const addOption = () => {
    const trimmed = input.trim();
    if (!trimmed) return;
    // Avoid duplicates (case-insensitive) so the dropdown stays clean.
    if (value.some((o) => o.toLowerCase() === trimmed.toLowerCase())) {
      setInput("");
      return;
    }
    onChange([...value, trimmed]);
    setInput("");
  };

  const removeOption = (index: number) => {
    onChange(value.filter((_, i) => i !== index));
  };

  return (
    <div className="space-y-1.5">
      <label
        htmlFor="field-builder-option"
        className="block text-[10px] font-medium uppercase tracking-widest text-on-muted"
      >
        {t("modules:fieldBuilder.options.label")}
      </label>
      <div className="flex gap-1.5">
        <Input
          id="field-builder-option"
          wrapperClassName="flex-1"
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              addOption();
            }
          }}
          placeholder={t("modules:fieldBuilder.options.placeholder")}
        />
      </div>
      {value.length > 0 && (
        <div className="flex flex-wrap gap-1.5 pt-0.5">
          {value.map((option, index) => (
            <span
              key={`${option}-${index}`}
              className="inline-flex items-center gap-1 rounded-full bg-surface-raised border border-border pl-2.5 pr-1 py-0.5 text-xs font-medium text-on"
            >
              {option}
              <button
                type="button"
                onClick={() => removeOption(index)}
                className="text-on-muted hover:text-red-500 rounded-full p-0.5 transition-colors"
                aria-label={t("modules:fieldBuilder.options.remove", {
                  name: option,
                })}
              >
                <X size={12} />
              </button>
            </span>
          ))}
        </div>
      )}
      {value.length === 0 && (
        <p className="text-[10px] text-on-muted italic">
          {t("modules:fieldBuilder.options.empty")}
        </p>
      )}
    </div>
  );
}
