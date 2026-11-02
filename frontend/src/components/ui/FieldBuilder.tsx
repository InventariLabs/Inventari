import {
  useCallback,
  useEffect,
  useRef,
  useState,
  useMemo,
  useId,
  type MutableRefObject,
} from "react";
import { Lock, Plus } from "lucide-react";
import { FieldDefinition } from "@/types";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import FieldBuilderHeader from "./FieldBuilderHeader";
import FieldBuilderFieldRow from "./FieldBuilderFieldRow";
import FieldBuilderFieldForm from "./FieldBuilderFieldForm";
import type { FieldFormValues } from "./FieldBuilderFieldForm";
import { needsOptions, type FieldType } from "./fieldTypes";

/**
 * Settles the field the reader typed but did not confirm, for the form that
 * holds the builder to call when it saves.
 *
 * Returns the fields the form should save — the builder's own, with the
 * pending field added (or its edit applied) when it is valid — or `null`
 * when the field is unfinished and the save has to stop: the builder has
 * already said what is missing and left its form open.
 */
export type FieldBuilderCommit = () => FieldDefinition[] | null;

/**
 * What a form holding a `FieldBuilder` needs to save it honestly.
 *
 * Pass `ref` to the builder as `commitRef`, and call `commit()` where the form
 * saves: it returns the fields to send (the form's own `fields` when the
 * builder holds nothing unconfirmed), or `null` when the reader left a field
 * half-typed and the save has to wait.
 */
export function useFieldBuilderCommit(fields: FieldDefinition[]) {
  const ref = useRef<FieldBuilderCommit | null>(null);
  const commit = useCallback(
    (): FieldDefinition[] | null => (ref.current ? ref.current() : fields),
    [fields],
  );
  return { ref, commit };
}

/** What the field form holds right now, unconfirmed. */
type PendingField =
  | { mode: "add"; values: FieldFormValues }
  | { mode: "edit"; key: string; values: FieldFormValues };

interface FieldBuilderProps {
  fields: FieldDefinition[];
  onChange: (fields: FieldDefinition[]) => void;
  /** Filled with the builder's {@link FieldBuilderCommit}; see
   *  `useFieldBuilderCommit`. */
  commitRef?: MutableRefObject<FieldBuilderCommit | null>;
  titleOverride?: string;
  subtitleOverride?: string;
  defaultOpen?: boolean;
}

export default function FieldBuilder({
  fields,
  onChange,
  commitRef,
  titleOverride,
  subtitleOverride,
  defaultOpen = false,
}: FieldBuilderProps) {
  const { t } = useTranslation(["common", "modules"]);
  const ownedHintId = useId();
  const [isOpen, setIsOpen] = useState(defaultOpen);
  const [isAddFormOpen, setIsAddFormOpen] = useState(false);
  const [editingKey, setEditingKey] = useState<string | null>(null);

  const TYPE_LABELS: Record<FieldType, string> = {
    text: t("modules:fieldBuilder.types.text"),
    number: t("modules:fieldBuilder.types.number"),
    date: t("modules:fieldBuilder.types.date"),
    textarea: t("modules:fieldBuilder.types.textarea"),
    file: t("modules:fieldBuilder.types.file", { defaultValue: "File" }),
    select: t("modules:fieldBuilder.types.select"),
    "multi-select": t("modules:fieldBuilder.types.multi-select"),
    boolean: t("modules:fieldBuilder.types.boolean"),
    money: t("modules:fieldBuilder.types.money"),
  };

  const visibleFields = useMemo(
    () => fields.filter((f) => f.label && f.label.trim() !== ""),
    [fields],
  );

  const pending = useRef<PendingField | null>(null);

  const missingOptions = (data: FieldFormValues) =>
    needsOptions(data.type) && (data.options ?? []).length === 0;

  /** The list with the edit applied, or the reason it cannot be. An edit
   *  that turns a field into a dropdown without options is refused like an
   *  add: saved, the server refused it and the reader lost the whole form. */
  const withEdit = (
    key: string,
    data: FieldFormValues,
  ): { fields: FieldDefinition[] } | { error: string } => {
    if (missingOptions(data)) {
      return { error: t("modules:fieldBuilder.errors.optionsRequired") };
    }
    return {
      fields: fields.map((f) => (f.key === key ? { ...f, ...data } : f)),
    };
  };

  /** The list with the new field on it, or the reason it cannot be. */
  const withNewField = (
    data: FieldFormValues,
  ): { fields: FieldDefinition[] } | { error: string } => {
    const options = data.options ?? [];
    if (missingOptions(data)) {
      return { error: t("modules:fieldBuilder.errors.optionsRequired") };
    }

    const key = data.label
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "_")
      .replace(/^_+|_+$/g, "")
      .substring(0, 30);

    if (fields.some((f) => f.key === key)) {
      return { error: t("modules:fieldBuilder.errors.alreadyExists") };
    }

    return {
      fields: [
        ...fields,
        {
          key,
          label: data.label,
          type: data.type,
          required: data.required,
          visible: true,
          // Built here, in the form builder: a field of the user's, not one of
          // the platform's.
          is_system: false,
          placeholder: null,
          ...(needsOptions(data.type) ? { options } : {}),
        },
      ],
    };
  };

  const handleSaveEdit = (key: string, data: FieldFormValues) => {
    const edited = withEdit(key, data);
    if ("error" in edited) {
      toast.error(edited.error);
      return;
    }
    onChange(edited.fields);
    setEditingKey(null);
  };

  const handleAddField = (data: FieldFormValues) => {
    const added = withNewField(data);
    if ("error" in added) {
      toast.error(added.error);
      return;
    }
    onChange(added.fields);
    setIsAddFormOpen(false);
  };

  // A field typed into the form and never confirmed was dropped when the
  // host saved, and the host reported success. The host asks here first.
  useEffect(() => {
    if (!commitRef) return;
    commitRef.current = () => {
      const draft = pending.current;
      if (!draft) return fields;
      const settled =
        draft.mode === "edit"
          ? withEdit(draft.key, draft.values)
          : withNewField(draft.values);
      if ("error" in settled) {
        toast.error(settled.error);
        return null;
      }
      onChange(settled.fields);
      if (draft.mode === "edit") setEditingKey(null);
      else setIsAddFormOpen(false);
      return settled.fields;
    };
    return () => {
      commitRef.current = null;
    };
  });

  const handleRemoveField = (key: string) => {
    if (editingKey === key) setEditingKey(null);
    onChange(fields.filter((f) => f.key !== key));
  };

  return (
    <div className="rounded-lg border border-border bg-surface-card transition-all">
      <FieldBuilderHeader
        isOpen={isOpen}
        onToggle={() => setIsOpen(!isOpen)}
        fields={fields}
        titleOverride={titleOverride}
        subtitleOverride={subtitleOverride}
      />

      {isOpen && (
        <div className="border-t border-border p-3 space-y-2">
          {visibleFields.map((field) => (
            <div key={field.key}>
              {editingKey === field.key ? (
                <FieldBuilderFieldForm
                  mode="edit"
                  field={field}
                  typeLabels={TYPE_LABELS}
                  onSubmit={(data) => handleSaveEdit(field.key, data)}
                  onCancel={() => setEditingKey(null)}
                  onDraftChange={(values) => {
                    pending.current = values
                      ? { mode: "edit", key: field.key, values }
                      : null;
                  }}
                />
              ) : (
                <FieldBuilderFieldRow
                  field={field}
                  typeLabel={TYPE_LABELS[field.type as FieldType] ?? field.type}
                  ownedHintId={ownedHintId}
                  onEdit={() => {
                    setEditingKey(field.key);
                    setIsAddFormOpen(false);
                  }}
                  onRemove={() => handleRemoveField(field.key)}
                />
              )}
            </div>
          ))}

          {visibleFields.some((f) => f.is_system) && (
            <p
              id={ownedHintId}
              className="flex items-center gap-1.5 px-1 text-xs text-on-muted"
            >
              <Lock size={12} aria-hidden="true" className="shrink-0" />
              {t("labels.catalogOwned", {
                defaultValue:
                  "Belongs to the product catalog — its name, type and requirement are fixed",
              })}
            </p>
          )}

          {!isAddFormOpen ? (
            <button
              type="button"
              onClick={() => {
                setIsAddFormOpen(true);
                setEditingKey(null);
              }}
              className="flex w-full items-center justify-center gap-2 rounded-lg border border-dashed border-border py-2.5 text-xs font-medium text-on-muted hover:border-primary-400 hover:text-primary-500 dark:hover:border-primary-600 transition-colors"
            >
              <Plus size={14} />
              {t("modules:fieldBuilder.addCustomField")}
            </button>
          ) : (
            <FieldBuilderFieldForm
              mode="add"
              typeLabels={TYPE_LABELS}
              onSubmit={handleAddField}
              onCancel={() => setIsAddFormOpen(false)}
              onDraftChange={(values) => {
                pending.current = values ? { mode: "add", values } : null;
              }}
            />
          )}
        </div>
      )}
    </div>
  );
}
