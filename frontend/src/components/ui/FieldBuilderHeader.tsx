import { ChevronDown, Settings2 } from "lucide-react";
import { useTranslation } from "react-i18next";
import { FieldDefinition } from "@/types";

interface FieldBuilderHeaderProps {
  isOpen: boolean;
  onToggle: () => void;
  fields: FieldDefinition[];
  titleOverride?: string;
  subtitleOverride?: string;
}

export default function FieldBuilderHeader({
  isOpen,
  onToggle,
  fields,
  titleOverride,
  subtitleOverride,
}: FieldBuilderHeaderProps) {
  const { t } = useTranslation(["common", "modules"]);

  return (
    <button
      type="button"
      onClick={onToggle}
      // Collapsed, this reads as a form control next to the selects above it,
      // so it carries their geometry (UI_GUIDELINES §2.10). The height is
      // stated minus 2px because the border belongs to the wrapper around this
      // button, not to the button: the box the eye compares is the outer one.
      // It stays a min-height — a subtitle makes the row genuinely two lines.
      className="flex w-full items-center justify-between gap-3 min-h-[calc(2.75rem-2px)] md:min-h-[calc(2.5rem-2px)] px-3 py-1.5 text-left hover:bg-surface-raised/50 transition-colors rounded-lg"
    >
      <div className="flex items-center gap-2">
        <div
          className={`p-1 rounded-lg transition-colors ${isOpen ? "bg-primary-100 text-primary-700 dark:bg-primary-900/40 dark:text-primary-500" : "bg-surface-raised text-on-secondary"}`}
        >
          <Settings2 size={16} />
        </div>
        <div>
          <h4 className="text-sm font-medium text-on">
            {titleOverride ??
              t("modules:fieldBuilder.title", {
                defaultValue: "Custom field definitions",
              })}
          </h4>
          {/* Only when it carries something the title does not. The generic
              "optional extra fields" line was a third caption over one
              collapsed section, under a section label that already said it. */}
          {(fields.length > 0 || subtitleOverride) && (
            <p className="text-[10px] font-medium uppercase tracking-widest text-on-muted">
              {fields.length > 0
                ? t("modules:fieldBuilder.fieldsCount", {
                    count: fields.length,
                    defaultValue: `${fields.length} defined fields`,
                  })
                : subtitleOverride}
            </p>
          )}
        </div>
      </div>
      {/* One disclosure indicator across the app: same icon, same size as
          `Select` and `NativeSelect` (UI_GUIDELINES §2.10). */}
      <ChevronDown
        size={18}
        className={`shrink-0 text-on-muted transition-transform duration-200 ${isOpen ? "rotate-180" : ""}`}
      />
    </button>
  );
}
