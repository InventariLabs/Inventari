import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import { useConfirm } from "@/hooks/useConfirm";
import { extractApiError } from "@/lib/errors";
import {
  useApplyDocumentPreset,
  useUpdateDocumentProfile,
} from "@/modules/warehouse/hooks/useDocumentProfile";
import type {
  DocumentProfile,
  DocumentProfileUpdate,
  TaxHandling,
} from "@/modules/warehouse/types";

const toString = (v: string | number | null | undefined): string => {
  if (v === null || v === undefined) return "";
  return String(v);
};

/**
 * The whole saved profile, as an update that puts every field back.
 *
 * A preset writes twelve of them, and six of those the settings page holds no
 * state for (`print_template`, `default_unit`, `visible_line_fields`, the
 * tax-id opinion, the pinned rate, the unit price), so the page's own draft
 * cannot undo an apply. The row can — this is the row, as an update.
 *
 * ``name`` is in it because ``apply_preset`` writes the preset's own name
 * onto the row: restoring the settings while leaving the row named after the
 * preset would leave the selector naming a configuration the row no longer
 * holds. */
function snapshotProfile(row: DocumentProfile): DocumentProfileUpdate {
  return {
    name: row.name,
    value_tracking_enabled: row.value_tracking_enabled,
    tax_handling: row.tax_handling as TaxHandling,
    default_tax_rate: toString(row.default_tax_rate) || null,
    require_partner_tax_id: row.require_partner_tax_id,
    require_unit_price: row.require_unit_price,
    confirm_shelf_by_scan: row.confirm_shelf_by_scan,
    numbering_format: row.numbering_format,
    number_padding: row.number_padding,
    type_labels: row.type_labels,
    default_unit: row.default_unit,
    visible_line_fields: row.visible_line_fields ?? undefined,
    print_template: row.print_template,
    default_currency: row.default_currency ?? null,
    approval_threshold: toString(row.approval_threshold) || null,
    approval_required_for_types: row.approval_required_for_types ?? [],
  };
}

interface UsePresetApplyArgs {
  /** The profile the query holds — the row an undo puts back. */
  profile: DocumentProfile | undefined;
  /** The page's own sync, so an undo leaves the controls where the row is. */
  syncLocalState: (profile: DocumentProfile) => void;
  applyPresetMutation: ReturnType<typeof useApplyDocumentPreset>;
  updateMutation: ReturnType<typeof useUpdateDocumentProfile>;
}

/**
 * Choosing a preset is a write the moment the option is picked — about a
 * dozen fields, six of which the settings page holds no state for and could
 * not put back by hand. So it asks first, and what it offers afterwards is
 * the row as it stood rather than the draft.
 *
 * The question and its dialog live here so the page stays a page; the caller
 * renders ``confirmDialogProps``.
 */
export function usePresetApply({
  profile: row,
  syncLocalState,
  applyPresetMutation,
  updateMutation,
}: UsePresetApplyArgs) {
  const { t } = useTranslation("warehouse");
  const { t: ct } = useTranslation("common");
  const { confirm, confirmDialogProps } = useConfirm();

  const undoPreset = (before: DocumentProfileUpdate) => {
    updateMutation.mutate(before, {
      onSuccess: (saved) => {
        syncLocalState(saved);
        toast.success(t("profile.presetUndone"));
      },
      onError: (error: unknown) =>
        toast.error(extractApiError(error, t("profile.presetUndoFailed"))),
    });
  };

  const applyPreset = async (presetName: string) => {
    const restoredName = row?.name ?? "";
    if (!presetName) return { declined: false, restoredName };
    const agreed = await confirm({
      title: t("profile.applyPresetConfirmTitle"),
      message: t("profile.applyPresetConfirmMessage", { name: presetName }),
      confirmLabel: t("profile.applyPreset"),
      cancelLabel: ct("actions.cancel"),
      variant: "danger",
    });
    if (!agreed) {
      // The select already shows the new name — the change fired before the
      // question — so a refusal puts it back to the row that still stands.
      return { declined: true, restoredName };
    }
    const before = row ? snapshotProfile(row) : null;
    applyPresetMutation.mutate(presetName, {
      onSuccess: (saved) => {
        syncLocalState(saved);
        toast.success(t("profile.applyPresetSuccess"), {
          action: before
            ? {
                label: t("profile.undoPreset"),
                onClick: () => undoPreset(before),
              }
            : undefined,
        });
      },
      onError: (error: unknown) =>
        toast.error(extractApiError(error, t("profile.applyPresetFailed"))),
    });
    return { declined: false, restoredName };
  };

  return { applyPreset, confirmDialogProps };
}
