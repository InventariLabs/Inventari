import { useHoldsAssignment } from "@/modules/equipment/hooks/useHoldsAssignment";
import { useState } from "react";
import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import {
  Edit2,
  Archive,
  PowerOff,
  Trash2,
  RotateCcw,
  ShieldCheck,
  LogOut,
  LogIn,
} from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Badge } from "@/components/ui/Badge";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { AssetStatusMenu } from "@/modules/equipment/components/AssetStatusMenu";
import type { EquipmentStatus } from "@/modules/equipment/components/AssetStatusBadge";
import { checkoutOfferable } from "@/modules/equipment/components/assetUtils";
import type { EquipmentAssignment } from "@/modules/equipment/api/equipment";

interface AssetDetailHeaderActionsProps {
  itemId: string;
  /** Null when the asset carries no status — the badge says unknown; the
   *  actions ask what can happen, not what the row claims to be. */
  status: string | null;
  isArchived: boolean;
  activeAssignment: EquipmentAssignment | null;
  approvalStatus:
    | { has_workflow: boolean; status?: string | null; consumed?: boolean }
    | undefined;
  /** Opens the dialog that asks for the approval of one checkout. */
  onRequestApproval: () => void;
  onChangeStatus: (status: EquipmentStatus) => void;
  bulkEditPending: boolean;
  onCheckout: () => void;
  onCheckin: (assignment: EquipmentAssignment) => void;
  onRestore: () => void;
  onPurge: () => void;
  onRetire: () => void;
  onArchive: () => void;
}

export function AssetDetailHeaderActions({
  itemId,
  status,
  isArchived,
  activeAssignment,
  approvalStatus,
  onRequestApproval,
  onChangeStatus,
  bulkEditPending,
  onCheckout,
  onCheckin,
  onRestore,
  onPurge,
  onRetire,
  onArchive,
}: AssetDetailHeaderActionsProps) {
  const { t } = useTranslation("equipment");
  const holdsIt = useHoldsAssignment(activeAssignment);
  const [returnStatus, setReturnStatus] = useState<EquipmentStatus | null>(
    null,
  );
  const cannotRetire = status === "DEPLOYED" || status === "RETIRED";
  const retireReason =
    status === "RETIRED"
      ? t("detail.cannot_retire_retired")
      : t("detail.cannot_retire_deployed");

  if (isArchived) {
    return (
      <div className="flex items-center gap-1">
        <Button
          variant="ghost"
          size="icon"
          onClick={onRestore}
          aria-label={t("actions.restore")}
          title={t("actions.restore")}
        >
          <RotateCcw size={16} />
        </Button>
        <Button
          variant="ghost"
          size="icon"
          onClick={onPurge}
          className="text-red-600 hover:text-red-700 hover:bg-red-50"
          aria-label={t("actions.purge")}
          title={t("actions.purge")}
        >
          <Trash2 size={16} />
        </Button>
      </div>
    );
  }

  return (
    <div className="flex flex-wrap items-center gap-1">
      {checkoutOfferable(status) && !activeAssignment && (
        <Button size="sm" leftIcon={<LogOut size={14} />} onClick={onCheckout}>
          {t("actions.checkout")}
        </Button>
      )}
      {activeAssignment && (
        <Button
          size="sm"
          leftIcon={<LogIn size={14} />}
          onClick={() => onCheckin(activeAssignment)}
        >
          {holdsIt
            ? t("assignments.checkin_modal.submit_holder")
            : t("actions.checkin")}
        </Button>
      )}
      {approvalStatus?.has_workflow &&
        (approvalStatus.status === "APPROVED" && !approvalStatus.consumed ? (
          // An approval waiting to be used opens the next checkout, so
          // there is nothing to ask for; a used one reads as needing a new
          // request, which is what the button below offers.
          <Badge variant="success" className="gap-1">
            <ShieldCheck size={14} />
            {t("approvals.approved_next_checkout")}
          </Badge>
        ) : (
          <Button
            variant="outline"
            size="sm"
            leftIcon={<ShieldCheck size={14} />}
            onClick={onRequestApproval}
            className="text-xs"
          >
            {approvalStatus.status && !approvalStatus.consumed
              ? t(
                  `approvals.status_${approvalStatus.status.toLowerCase()}`,
                  approvalStatus.status,
                )
              : t("approvals.request", "Request Approval")}
          </Button>
        ))}
      <AssetStatusMenu
        currentStatus={status as EquipmentStatus | null}
        onChangeStatus={(next) => {
          if (status === "RETIRED") setReturnStatus(next);
          else onChangeStatus(next);
        }}
        disabled={bulkEditPending}
      />
      <ConfirmDialog
        open={returnStatus !== null}
        title={t("detail.confirm_unretire")}
        message={t("detail.confirm_unretire_msg", {
          status: returnStatus
            ? t(`status.${returnStatus.toLowerCase()}`, returnStatus)
            : "",
        })}
        confirmLabel={t("detail.confirm_unretire_action")}
        cancelLabel={t("common:actions.cancel", "Cancel")}
        onConfirm={() => {
          if (returnStatus) onChangeStatus(returnStatus);
          setReturnStatus(null);
        }}
        onCancel={() => setReturnStatus(null)}
      />
      <Link to={`/equipment/${itemId}/edit`}>
        <Button
          variant="ghost"
          size="icon"
          aria-label={t("actions.edit")}
          title={t("actions.edit")}
        >
          <Edit2 size={16} />
        </Button>
      </Link>
      {/* ui-pattern: destructive-as-neutral — retiring is a status change,
          not a deletion: the asset stays in the register and the amber this
          button already wears at rest says so without claiming it is gone */}
      <Button
        variant="ghost"
        size="icon"
        disabled={cannotRetire}
        onClick={onRetire}
        className="text-amber-600 hover:text-amber-700 hover:bg-amber-50 disabled:text-on-muted disabled:opacity-50"
        aria-label={cannotRetire ? retireReason : t("actions.retire")}
        title={cannotRetire ? retireReason : t("actions.retire")}
      >
        <PowerOff size={16} />
      </Button>
      {/* A phone shows the reason too, on a line of its own: a disabled
          icon alone does not say why it is grey, and a tooltip never opens
          under a thumb. */}
      {cannotRetire && (
        <p className="order-last basis-full text-xs text-on-muted sm:order-none sm:basis-auto sm:self-center">
          {retireReason}
        </p>
      )}
      <Button
        variant="ghostDanger"
        size="icon"
        onClick={onArchive}
        aria-label={t("actions.archive", "Archive")}
        title={t("actions.archive", "Archive")}
      >
        <Archive size={16} />
      </Button>
    </div>
  );
}
