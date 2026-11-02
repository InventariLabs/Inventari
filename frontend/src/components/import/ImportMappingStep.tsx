import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { Check } from "lucide-react";
import { Select } from "@/components/ui/Select";
import { ImportPreviewTable } from "./ImportPreviewTable";
import type { ImportMapping, ImportPreviewRow, MappingField } from "./types";

interface ImportMappingStepProps {
  file: File | null;
  headers: string[];
  fields: MappingField[];
  mapping: ImportMapping;
  /** The first rows of the source, shown under the grid. */
  previewRows?: ImportPreviewRow[];
  onMappingChange: (mapping: ImportMapping) => void;
  /** Sits beside the file name: a preset button, say. */
  headerExtras?: ReactNode;
  /** Sits under the grid: notes and options specific to the entity. */
  children?: ReactNode;
}

export function ImportMappingStep({
  file,
  headers,
  fields,
  mapping,
  previewRows = [],
  onMappingChange,
  headerExtras,
  children,
}: ImportMappingStepProps) {
  const { t } = useTranslation(["common"]);
  return (
    <div className="space-y-6">
      {/* File confirmation */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2 text-sm font-semibold text-on-muted uppercase tracking-widest">
          <Check className="text-accent-500" size={16} />
          {t("common:import.fileAnalyzed")}:{" "}
          <span className="text-on">{file?.name}</span>
        </div>
        {headerExtras}
      </div>

      {/* Mapping form */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-6 bg-surface/50 p-6 rounded-xl border border-border">
        {fields.map((field) => (
          <div key={field.key} className="space-y-1.5">
            <Select
              label={field.label}
              required={field.required}
              value={mapping[field.key] || ""}
              onChange={(id) =>
                onMappingChange({
                  ...mapping,
                  [field.key]: id === "__skip__" ? "" : id,
                })
              }
              options={[
                { id: "__skip__", name: t("common:import.skipColumn") },
                ...headers.map((h) => ({ id: h, name: h })),
              ]}
            />
          </div>
        ))}
      </div>

      <ImportPreviewTable
        rows={previewRows}
        fields={fields}
        mapping={mapping}
      />

      {children}
    </div>
  );
}
