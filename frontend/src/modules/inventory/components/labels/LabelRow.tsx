import { Eye, Tag, Trash2 } from "lucide-react";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { useFreeLabel } from "@/modules/inventory/hooks/useFreeLabel";
import { useTranslation } from "react-i18next";
import type { TFunction } from "i18next";
import { Button } from "@/components/ui/Button";
import { Checkbox } from "@/components/ui/Checkbox";
import { useLabelPurposeName } from "@/modules/inventory/hooks/useLabelPurposeName";
import {
  labelState,
  useLabelStateName,
} from "@/modules/inventory/hooks/useLabelStateName";
import type { LabelPool } from "@/types";

interface LabelRowProps {
  label: LabelPool;
  isSelected: boolean;
  onToggleSelect: () => void;
  onPreviewSingle: () => void;
  onDelete: (e: React.MouseEvent) => void;
  /** Whether to offer the delete — it asks for `items:write`. */
  canWrite?: boolean;
  /** False when no label on the page has a description or an assigned item —
   * the table then leaves that column out entirely. */
  showDescription?: boolean;
}

export function LabelRow({
  label,
  isSelected,
  onToggleSelect,
  onPreviewSingle,
  onDelete,
  canWrite = true,
  showDescription = true,
}: LabelRowProps) {
  const { t } = useTranslation(["labels", "common"]);
  const purposeName = useLabelPurposeName();
  const stateName = useLabelStateName();
  const state = labelState(label);
  return (
    <tr
      data-testid="label-row"
      // A tap on the checkbox's 44px square is the box's own click (the
      // label forwards it); counting it here as well toggled the row twice.
      onClick={(e) => {
        if (!(e.target as HTMLElement).closest("label")) onToggleSelect();
      }}
      className={`group cursor-pointer transition-colors ${
        isSelected
          ? "bg-accent-500/10 border-l-2 border-l-accent-500"
          : "hover:bg-surface-raised/50"
      }`}
    >
      <td className="pl-3 sm:pl-5 pr-0 py-3 sm:py-4 w-10">
        <Checkbox
          touchTarget
          checked={isSelected}
          onChange={onToggleSelect}
          onClick={(e) => e.stopPropagation()}
          aria-label={t("labels:actions.selectLabel", {
            code: label.short_code,
          })}
          className="w-4 h-4 accent-primary-500"
        />
      </td>
      <td className="px-2 sm:px-4 py-3 sm:py-4">
        <div className="font-mono font-bold text-sm text-on">
          {label.short_code}
        </div>
        {showDescription && (
          <div className="sm:hidden text-xs text-on-secondary truncate max-w-[120px] mt-0.5">
            {label.is_assigned && label.assigned_item_name
              ? label.assigned_item_name
              : label.description || "-"}
          </div>
        )}
      </td>
      {showDescription && (
        <td className="px-2 sm:px-4 py-3 sm:py-4 hidden sm:table-cell">
          {label.is_assigned && label.assigned_item_name ? (
            <div className="flex flex-col">
              <span className="font-semibold text-on">
                {label.assigned_item_name}
              </span>
              <span className="text-xs text-on-muted font-medium">
                {/* The category the assigned item is filed under speaks
                    first: an asset's label reads "Equipment in use", a
                    product's keeps "Product in use". What the batch was
                    printed for cannot answer — the assignment outlived it. */}
                {assignmentSubtitle(label, t, purposeName)}
              </span>
            </div>
          ) : (
            <span className="text-on-secondary text-sm">
              {label.description || "-"}
            </span>
          )}
        </td>
      )}
      <td className="px-2 sm:px-4 py-3 sm:py-4 hidden md:table-cell">
        <span className="text-xs font-medium uppercase tracking-wider text-on-muted">
          {/* What the label points at, not how it was made: a GENERIC label
              printed as an asset label opens the equipment form, and the
              column that says "Product" about it is the one lie a printed
              sheet cannot be checked against — so an assigned item's own
              category names the purpose when the two differ. */}
          {label.is_assigned && label.assigned_item_context_tag
            ? purposeName(label.assigned_item_context_tag)
            : label.label_type === "CATEGORY"
              ? t("generateModal.types.category")
              : purposeName(label.context_tag)}
        </span>
      </td>
      <td className="px-2 sm:px-4 py-3 sm:py-4">
        <div className="flex gap-1 sm:gap-1.5 flex-wrap">
          <span
            className={`text-xs font-medium px-1.5 sm:px-2 py-0.5 rounded-full uppercase border ${
              state === "ASSIGNED"
                ? "bg-accent-50 text-accent-700 border-accent-100"
                : "bg-surface-raised text-on-secondary border-border"
            }`}
          >
            {stateName(state)}
          </span>
        </div>
      </td>
      <td className="px-2 sm:px-4 py-3 sm:py-4 text-right">
        <div className="flex justify-end gap-1 sm:gap-2">
          <Button
            variant="ghost"
            size="icon"
            onClick={(e) => {
              e.stopPropagation();
              onPreviewSingle();
            }}
            className="text-accent-700 hover:bg-accent-50"
            title={t("labels:actions.preview")}
            aria-label={t("labels:actions.preview")}
          >
            <Eye size={16} />
          </Button>
          {label.is_assigned && canWrite && <FreeLabelButton label={label} />}
          {!label.is_assigned && canWrite && (
            <Button
              data-testid="label-delete-btn"
              variant="ghost"
              size="icon"
              onClick={onDelete}
              className="text-on-secondary hover:bg-surface-raised"
              title={t("labels:actions.deleteLabel", {
                code: label.short_code,
              })}
              aria-label={t("labels:actions.deleteLabel", {
                code: label.short_code,
              })}
            >
              <Trash2 size={16} />
            </Button>
          )}
        </div>
      </td>
    </tr>
  );
}

/** A deleted item keeps its name and kind in the label's history, but is no
 * longer "in use". */
function assignmentSubtitle(
  label: LabelPool,
  t: TFunction,
  purposeName: (contextTag?: string | null) => string,
): string {
  const tag = label.assigned_item_context_tag;
  const purpose = tag ? purposeName(tag) : "";
  if (label.is_item_deleted) {
    return tag
      ? t("status.purposeDeleted", { purpose })
      : t("status.itemDeleted");
  }
  return tag ? t("status.purposeInUse", { purpose }) : t("status.itemInUse");
}

/**
 * Takes the label off the product it is on. Its own component so that only a
 * label in use carries the question and the request behind it.
 */
function FreeLabelButton({ label }: { label: LabelPool }) {
  const { t } = useTranslation("labels");
  const { freeLabel, isFreeing, confirmDialogProps } = useFreeLabel();
  const name = t("actions.freeLabelNamed", { code: label.short_code });
  return (
    <>
      <Button
        data-testid="label-free-btn"
        variant="ghost"
        size="icon"
        disabled={isFreeing}
        onClick={(e) => {
          e.stopPropagation();
          void freeLabel(label.short_code, label.assigned_item_name);
        }}
        className="text-on-secondary hover:bg-surface-raised"
        title={name}
        aria-label={name}
      >
        <Tag size={16} />
      </Button>
      <ConfirmDialog {...confirmDialogProps} />
    </>
  );
}
