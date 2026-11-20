import { useTranslation } from "react-i18next";
import { CheckCircle2, Copy, Pencil } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { useCanWrite } from "@/hooks/useCanWrite";
import { CancelRunButton } from "@/modules/maker/components/CancelRunButton";
import { ReverseRunAction } from "@/modules/maker/components/ReverseRunAction";
import { ProductionStatusBadge } from "@/modules/maker/components/ProductionStatusBadge";
import { FinishRunAction } from "@/modules/maker/components/FinishRunAction";
import { StartRunAction } from "@/modules/maker/components/StartRunAction";
import type {
  ProductionOrder,
  ShortageEntry,
} from "@/modules/maker/types/maker";

interface Props {
  order: ProductionOrder;
  canManage: boolean;
  canWrite: boolean;
  isDuplicating: boolean;
  onEdit: () => void;
  onCancel: () => void;
  onComplete: () => void;
  onDuplicate: () => void;
  onShortage: (shortages: ShortageEntry[], shortAtCreate: boolean) => void;
}

/**
 * The status and the actions of a run, by where it stands: a draft is edited,
 * started or completed in one step; a run in progress is finished or
 * cancelled; a completed one is undone. flex-wrap, not smaller buttons: the
 * row holds the status badge and up to five actions, and on a phone it used
 * to run past the edge — "Complete run" cut mid-label, "Duplicate" invisible.
 * Same pattern as DocumentActionButtons. Every action but the manager's own
 * (cancel, undo) is for an account that may write; a reader sees the status
 * alone, and the page above says why. Starting, completing, finishing,
 * cancelling a run in progress and undoing one move stock, so their endpoints
 * ask for items:write on top of the module's own key, and the buttons ask the
 * same.
 */
export function ProductionRunActions({
  order,
  canManage,
  canWrite,
  isDuplicating,
  onEdit,
  onCancel,
  onComplete,
  onDuplicate,
  onShortage,
}: Props) {
  const { t } = useTranslation("maker");
  const isDraft = order.status === "DRAFT";
  const isInProgress = order.status === "IN_PROGRESS";
  const canMoveStock = useCanWrite("items");

  return (
    <div className="flex flex-wrap items-center gap-3">
      <ProductionStatusBadge status={order.status} />
      {isDraft && canWrite && (
        <Button
          variant="outline"
          onClick={onEdit}
          leftIcon={<Pencil size={16} />}
          data-testid="maker-detail-edit-button"
        >
          {t("detail.edit", { defaultValue: "Edit" })}
        </Button>
      )}
      {(isDraft || (isInProgress && canMoveStock)) && (
        <CancelRunButton
          canManage={canManage}
          canWrite={canWrite}
          onCancel={onCancel}
        />
      )}
      {isDraft && canWrite && canMoveStock && (
        <>
          <StartRunAction order={order} onShortage={onShortage} />
          <Button
            onClick={onComplete}
            leftIcon={<CheckCircle2 size={16} />}
            data-testid="maker-detail-complete-button"
          >
            {t("detail.complete", { defaultValue: "Complete run" })}
          </Button>
        </>
      )}
      {isInProgress && canWrite && canMoveStock && (
        <FinishRunAction order={order} />
      )}
      <ReverseRunAction order={order} />
      {canWrite && (
        <Button
          variant="outline"
          onClick={onDuplicate}
          disabled={isDuplicating}
          leftIcon={<Copy size={16} />}
          data-testid="maker-detail-duplicate-button"
        >
          {t("detail.duplicate", { defaultValue: "Duplicate" })}
        </Button>
      )}
    </div>
  );
}
