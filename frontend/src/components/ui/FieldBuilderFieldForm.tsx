import { useEffect, useRef, useState } from "react";
import { Check, Plus, X } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Input } from "@/components/ui/Input";
import { NativeSelect } from "@/components/ui/NativeSelect";
import { FieldDefinition } from "@/types";
import FieldBuilderRequiredToggle from "./FieldBuilderRequiredToggle";
import FieldBuilderOptionsEditor from "./FieldBuilderOptionsEditor";
import { needsOptions, type FieldType } from "./fieldTypes";

export interface FieldFormValues {
  label: string;
  type: FieldType;
  required: boolean;
  options?: string[];
}

/**
 * The options with the text left in the add box appended. Typed and never
 * confirmed with Enter, it was neither on the list nor in the way of the save,
 * which then answered "requires at least one option" beside a box that held
 * one. The reader meant it; saving settles it.
 */
function withTypedOption(options: string[], typed: string): string[] {
  const text = typed.trim();
  if (!text || options.some((o) => o.toLowerCase() === text.toLowerCase())) {
    return options;
  }
  return [...options, text];
}

/** The payload of the form: options only travel with a type that has them. */
function formValues(
  label: string,
  type: FieldType,
  required: boolean,
  options: string[],
): FieldFormValues {
  return {
    label: label.trim(),
    type,
    required,
    ...(needsOptions(type) ? { options } : {}),
  };
}

interface FieldBuilderFieldFormProps {
  /** Adding a field, or editing one that exists. Decides the chrome only. */
  mode: "add" | "edit";
  /** The field being edited. Absent when adding. */
  field?: FieldDefinition;
  typeLabels: Record<FieldType, string>;
  onSubmit: (values: FieldFormValues) => void;
  onCancel: () => void;
  /** What the form holds, as it changes — `null` once it holds nothing worth
   *  confirming (no label) or is gone. The builder reads it when the form
   *  around it saves. */
  onDraftChange?: (values: FieldFormValues | null) => void;
}

/**
 * The one form behind "add a custom field" and "edit this one".
 *
 * They were two components with the same four pieces of state, the same
 * payload, and the same rule about clearing the options when the type
 * changes — kept in step by hand. What actually differs is the chrome: the
 * add form carries a title and a close cross, the edit form a Cancel next
 * to its Save.
 */
export default function FieldBuilderFieldForm({
  mode,
  field,
  typeLabels,
  onSubmit,
  onCancel,
  onDraftChange,
}: FieldBuilderFieldFormProps) {
  const { t } = useTranslation(["common", "modules"]);
  const [label, setLabel] = useState(field?.label ?? "");
  const [type, setType] = useState<FieldType>(
    (field?.type as FieldType) ?? "text",
  );
  const [required, setRequired] = useState(field?.required ?? false);
  const [options, setOptions] = useState<string[]>(field?.options ?? []);
  const [typedOption, setTypedOption] = useState("");

  const isAdd = mode === "add";
  const showOptionsEditor = needsOptions(type);

  const submit = () => {
    if (!label.trim()) return;
    onSubmit(
      formValues(label, type, required, withTypedOption(options, typedOption)),
    );
  };

  const reportDraft = useRef(onDraftChange);
  useEffect(() => {
    reportDraft.current = onDraftChange;
  });
  useEffect(() => {
    reportDraft.current?.(
      label.trim()
        ? formValues(
            label,
            type,
            required,
            withTypedOption(options, typedOption),
          )
        : null,
    );
  }, [label, type, required, options, typedOption]);
  useEffect(() => () => reportDraft.current?.(null), []);

  return (
    <div
      className={
        isAdd
          ? "rounded-xl border border-border bg-surface p-3 space-y-3"
          : "rounded-xl border border-primary-400 dark:border-primary-600 bg-surface p-3 space-y-3"
      }
    >
      {isAdd && (
        <div className="flex items-center justify-between">
          <span className="text-[10px] font-medium uppercase tracking-widest text-on-muted">
            {t("modules:fieldBuilder.addCustomField")}
          </span>
          <button
            type="button"
            onClick={onCancel}
            className="text-on-muted hover:text-on"
          >
            <X size={14} />
          </button>
        </div>
      )}
      <div className="grid grid-cols-2 items-end gap-2">
        <div>
          <Input
            label={t("modules:fieldBuilder.fieldLabel", {
              defaultValue: "Label",
            })}
            type="text"
            value={label}
            onChange={(e) => setLabel(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && submit()}
            placeholder={
              isAdd ? t("modules:fieldBuilder.placeholder") : undefined
            }
            autoFocus
          />
        </div>
        <div>
          <NativeSelect
            label={t("modules:fieldBuilder.dataType", { defaultValue: "Type" })}
            value={type}
            onChange={(e) => {
              const next = e.target.value as FieldType;
              setType(next);
              // Clear options when switching away from an options-bearing type
              // so stale data is never persisted on a non-options field.
              if (!needsOptions(next)) {
                setOptions([]);
                setTypedOption("");
              }
            }}
          >
            {(Object.keys(typeLabels) as FieldType[]).map((k) => (
              <option key={k} value={k}>
                {typeLabels[k]}
              </option>
            ))}
          </NativeSelect>
        </div>
      </div>
      {showOptionsEditor && (
        <FieldBuilderOptionsEditor
          value={options}
          onChange={setOptions}
          input={typedOption}
          onInputChange={setTypedOption}
        />
      )}
      <div
        className={
          isAdd
            ? "flex items-center justify-between pt-1 border-t border-border"
            : "flex items-center justify-between"
        }
      >
        <FieldBuilderRequiredToggle checked={required} onChange={setRequired} />
        {isAdd ? (
          <button
            type="button"
            onClick={submit}
            disabled={!label.trim()}
            className="flex items-center gap-1.5 px-4 py-2 text-xs font-medium rounded-lg bg-primary-700 dark:bg-primary-800 text-white hover:bg-primary-800 dark:hover:bg-primary-900 disabled:opacity-40 transition-colors"
          >
            <Plus size={14} />
            {t("modules:fieldBuilder.addField", { defaultValue: "Add" })}
          </button>
        ) : (
          <div className="flex gap-2">
            <button
              type="button"
              onClick={onCancel}
              className="px-3 py-1.5 text-xs rounded-lg border border-border text-on-secondary hover:bg-surface-raised transition-colors"
            >
              {t("common:actions.cancel")}
            </button>
            <button
              type="button"
              onClick={submit}
              disabled={!label.trim()}
              className="flex items-center gap-1 px-3 py-1.5 text-xs rounded-lg bg-primary-700 dark:bg-primary-800 text-white hover:bg-primary-800 dark:hover:bg-primary-900 disabled:opacity-40 transition-colors"
            >
              <Check size={12} />
              {t("common:actions.save")}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
