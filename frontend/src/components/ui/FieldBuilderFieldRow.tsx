import { useId } from "react";
import { Lock, Pencil, X } from "lucide-react";
import { useTranslation } from "react-i18next";
import { FieldDefinition } from "@/types";

interface FieldBuilderFieldRowProps {
  field: FieldDefinition;
  typeLabel: string;
  /** Id of the line that says why a catalog-owned row is locked. */
  ownedHintId: string;
  onEdit: () => void;
  onRemove: () => void;
}

export default function FieldBuilderFieldRow({
  field,
  typeLabel,
  ownedHintId,
  onEdit,
  onRemove,
}: FieldBuilderFieldRowProps) {
  const { t } = useTranslation(["common", "items"]);
  const nameId = useId();

  // A system field is named by the catalog (items:fields.*): the label stored
  // on the field is whatever language the seeding ran in, and every screen
  // that reads the field shows the catalog's word instead. So the row shows
  // that word too — the builder and the form must not name one field two
  // ways. The server refuses a rename and the platform re-declares the field's
  // type and requirement whenever its module is enabled, so the row offers no
  // controls: edits made here would be undone, not kept.
  const locked = Boolean(field.is_system);
  const name = locked
    ? t(`items:fields.${field.key}`, { defaultValue: field.label })
    : field.label;

  return (
    <div className="group flex items-center justify-between bg-surface rounded-xl border border-border px-3 py-2.5 hover:border-border-hover hover:bg-surface-raised transition-colors">
      {locked ? (
        <div
          role="group"
          tabIndex={0}
          aria-labelledby={nameId}
          aria-describedby={ownedHintId}
          className="flex items-center gap-2.5 flex-1 min-w-0 text-left cursor-default rounded-md focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary-500"
        >
          <span id={nameId} className="font-semibold text-sm text-on truncate">
            {name}
          </span>
          <span className="shrink-0 text-[10px] font-medium text-on-secondary bg-surface-raised border border-border px-1.5 py-0.5 rounded uppercase">
            {typeLabel}
          </span>
          {field.required ? (
            <span className="shrink-0 text-[10px] font-medium text-red-500 uppercase">
              {t("labels.required", { defaultValue: "Required" })}
            </span>
          ) : (
            <span className="shrink-0 text-[10px] text-on-muted uppercase">
              {t("optional", { defaultValue: "Optional" })}
            </span>
          )}
          <Lock
            size={12}
            aria-hidden="true"
            className="ml-auto shrink-0 text-on-muted"
          />
        </div>
      ) : (
        <>
          <button
            type="button"
            onClick={onEdit}
            className="flex items-center gap-2.5 flex-1 min-w-0 text-left"
          >
            <span className="font-semibold text-sm text-on truncate">
              {field.label}
            </span>
            <span className="shrink-0 text-[10px] font-medium text-on-secondary bg-surface-raised border border-border px-1.5 py-0.5 rounded uppercase">
              {typeLabel}
            </span>
            {field.required ? (
              <span className="shrink-0 text-[10px] font-medium text-red-500 uppercase">
                {t("labels.required", { defaultValue: "Required" })}
              </span>
            ) : (
              <span className="shrink-0 text-[10px] text-on-muted uppercase">
                {t("optional", { defaultValue: "Optional" })}
              </span>
            )}
            <Pencil
              size={12}
              className="ml-auto shrink-0 text-on-muted transition-opacity md:opacity-0 md:group-hover:opacity-100 md:group-focus-within:opacity-100"
            />
          </button>
          <button
            type="button"
            onClick={onRemove}
            className="ml-2 p-1.5 text-on-muted hover:text-red-500 hover:bg-red-50 dark:hover:bg-red-950/40 rounded-lg transition-colors shrink-0"
            title={t("actions.delete")}
          >
            <X size={14} />
          </button>
        </>
      )}
    </div>
  );
}
