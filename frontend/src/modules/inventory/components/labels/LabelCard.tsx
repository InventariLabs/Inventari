import { Eye, Home, Package, Tag, Trash2 } from "lucide-react";
import { memo } from "react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/Button";
import { formatDate, formatDateTime } from "@/utils/helpers";
import type { LabelPool } from "@/types";
import {
  labelState,
  useLabelStateName,
} from "@/modules/inventory/hooks/useLabelStateName";
import { formatQuantityLocalized } from "@/lib/i18nHelpers";
import { useLabelPurposeName } from "@/modules/inventory/hooks/useLabelPurposeName";

interface LabelCardProps {
  label: LabelPool;
  isSelected: boolean;
  onToggleSelect: () => void;
  onPreviewSingle: () => void;
  onDelete: (e: React.MouseEvent) => void;
  /** Whether to offer the delete — it asks for `items:write`. */
  canWrite?: boolean;
}

export const LabelCard = memo(function LabelCard({
  label,
  isSelected,
  onToggleSelect,
  onPreviewSingle,
  onDelete,
  canWrite = true,
}: LabelCardProps) {
  const { t } = useTranslation(["labels", "common"]);
  const stateName = useLabelStateName();
  const purposeName = useLabelPurposeName();
  const state = labelState(label);

  return (
    <div
      data-testid="label-card"
      onClick={onToggleSelect}
      className={`relative bg-surface-card rounded-2xl p-4 border transition-all cursor-pointer group ${
        isSelected
          ? "border-accent-200 bg-accent-50/30"
          : "border-transparent shadow-sm hover:border-border"
      }`}
    >
      <div className="flex items-start justify-between mb-3">
        <div className="p-2 rounded-xl bg-surface text-on-secondary border border-border">
          {label.label_type === "STORAGE" ? (
            <Home size={20} />
          ) : label.label_type === "CATEGORY" ? (
            <Tag size={20} />
          ) : (
            <Package size={20} />
          )}
        </div>

        <div className="flex items-center gap-2">
          <span
            className={`text-xs font-medium px-2 py-0.5 rounded-full uppercase border ${
              state === "ASSIGNED"
                ? "bg-accent-50 text-accent-700 border-accent-100"
                : "bg-surface-raised text-on-secondary border-border"
            }`}
            title={
              label.printed_at
                ? t("status.printedAt", {
                    date: formatDateTime(label.printed_at),
                  })
                : undefined
            }
          >
            {stateName(state)}
          </span>
        </div>
      </div>

      <h3 className="font-mono font-semibold text-lg text-on">
        {label.short_code}
      </h3>
      <p className="text-xs text-on-secondary mt-1 line-clamp-1">
        {label.is_assigned && label.assigned_item_name ? (
          <span className="font-medium text-accent-700">
            {label.assigned_item_name}
          </span>
        ) : (
          label.description ||
          (label.label_type === "GENERIC"
            ? purposeName(label.context_tag)
            : label.label_type)
        )}
      </p>

      <div className="mt-4 flex items-center justify-between text-xs text-on-secondary font-medium uppercase tracking-wider">
        <span>
          {label.is_assigned && label.assigned_item_quantity !== undefined ? (
            <>
              {t("quickAdd.inStock")}:{" "}
              <span className="text-accent-700 font-semibold">
                {formatQuantityLocalized(
                  t,
                  label.assigned_item_quantity,
                  label.assigned_item_unit,
                )}
              </span>
            </>
          ) : (
            <>
              {t("status.scans")}:{" "}
              <span className="font-semibold">{label.scan_count}</span>
            </>
          )}
        </span>
        <span className="opacity-60">{formatDate(label.created_at)}</span>
      </div>

      {!label.is_assigned && (
        <div className="absolute -top-2 -right-2 flex gap-1 shadow-md rounded-full">
          <Button
            variant="outline"
            size="icon"
            onClick={(e) => {
              e.stopPropagation();
              onPreviewSingle();
            }}
            className="bg-surface-card border-accent-100 text-accent-700 hover:bg-accent-50 rounded-full"
            title={t("labels:actions.preview")}
            aria-label={t("labels:actions.preview")}
          >
            <Eye size={14} />
          </Button>
          {canWrite && (
            <Button
              data-testid="label-delete-btn"
              variant="outline"
              size="icon"
              onClick={onDelete}
              className="bg-surface-card border-border text-on-secondary hover:bg-surface rounded-full"
              title={t("labels:actions.deleteLabel", {
                code: label.short_code,
              })}
              aria-label={t("labels:actions.deleteLabel", {
                code: label.short_code,
              })}
            >
              <Trash2 size={14} />
            </Button>
          )}
        </div>
      )}
    </div>
  );
});
