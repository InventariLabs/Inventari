import { useState } from "react";
import { toast } from "sonner";
import { SheetActions } from "@/components/ui/Sheet";
import { useTranslation } from "react-i18next";
import { Loader2, RotateCcw } from "lucide-react";
import { Button } from "@/components/ui/Button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/Dialog";
import { ChoiceGroup } from "@/components/ui/ChoiceGroup";
import { Textarea } from "@/components/ui/Textarea";
import {
  checkinConditionOptions,
  statusAfterCheckin,
  type CheckinCondition,
} from "@/modules/equipment/components/checkinConditions";
import { ReturnLocationField } from "@/modules/equipment/components/ReturnLocationField";
import { useCheckin } from "@/modules/equipment/hooks/useEquipment";
import { useIsSignedInAs } from "@/module-sdk";

/**
 * What checking in actually needs to know — narrower than
 * `EquipmentAssignment`, which stays assignable to it.
 *
 * The holder's own list describes the same assignment with a different shape
 * (`MyAsset`), and demanding the wide type there would mean inventing fields
 * the endpoint does not send just to satisfy a signature.
 */
export interface CheckinTarget {
  id: string;
  item_name: string;
  assigned_to_name?: string | null;
  assigned_to_email?: string | null;
  partner_name?: string | null;
  /** The holder, person or place, resolved by the backend. */
  holder_name?: string | null;
  holder_kind?: "person" | "location" | null;
}

interface CheckinModalProps {
  assignment: CheckinTarget;
  /** The asset's own location — where the return puts it unless told otherwise. */
  homeLocationId?: string | null;
  /**
   * The holder is handing it back, not a manager receiving it: the dialog
   * speaks the holder's verb. A viewer whose own address is the assignment's
   * is the holder without being told, so the asset page words it right too.
   */
  byHolder?: boolean;
  onClose: () => void;
}

export function CheckinModal({
  assignment,
  homeLocationId,
  byHolder: handedBack = false,
  onClose,
}: CheckinModalProps) {
  const { t } = useTranslation("equipment");
  const checkinMutation = useCheckin();
  const holdsIt = useIsSignedInAs(assignment.assigned_to_email);
  const byHolder =
    handedBack || (assignment.holder_kind !== "location" && holdsIt);

  const title = byHolder
    ? t("assignments.checkin_modal.title_holder")
    : t("assignments.checkin_modal.title");
  const submitLabel = byHolder
    ? t("assignments.checkin_modal.submit_holder")
    : t("assignments.checkin_modal.submit");
  const [condition, setCondition] = useState<CheckinCondition>("GOOD");
  const [notes, setNotes] = useState("");
  const [returnTo, setReturnTo] = useState(homeLocationId ?? "");

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    checkinMutation.mutate(
      {
        assignmentId: assignment.id,
        data: {
          checkin_condition: condition,
          checkin_notes: notes || undefined,
          return_location_id: returnTo || undefined,
        },
      },
      {
        onSuccess: () => {
          // A return that sent the asset to the workshop says so: the status
          // it lands in is the consequence the person chose.
          const status = statusAfterCheckin(condition);
          toast.success(
            status === "AVAILABLE"
              ? t("assignments.checkin_done", { asset: assignment.item_name })
              : t("assignments.checkin_done_status", {
                  asset: assignment.item_name,
                  status: t(`status.${status.toLowerCase()}`),
                }),
          );
          onClose();
        },
      },
    );
  };

  // Radix Dialog provides role="dialog", ESC, focus trap, scroll lock,
  // and the canonical var(--z-modal) z-index token. The scroll contract
  // is retained: form body has min-h-0 flex-1 overflow-y-auto
  // so the action buttons always stay inside the viewport.
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent
        className="w-full max-w-md gap-0 p-0 rounded-t-3xl sm:rounded-2xl max-h-[90vh] flex flex-col overflow-hidden"
        data-testid="checkin-modal-card"
      >
        <DialogHeader className="flex flex-row items-center gap-3 border-b border-border px-5 py-4">
          <RotateCcw size={18} className="text-primary-500" />
          <DialogTitle className="font-semibold text-on">{title}</DialogTitle>
          <DialogDescription className="sr-only">{title}</DialogDescription>
        </DialogHeader>

        <div className="px-5 pt-3 pb-1">
          <p className="text-sm font-medium text-on">{assignment.item_name}</p>
          {/* A line that names nobody is worse than no line: "Assigned to:"
              with an empty tail read as a missing answer, not as the holder's
              own check-in. The holder's screen passes its own "you". */}
          {!byHolder &&
            (assignment.holder_name ||
              assignment.partner_name ||
              assignment.assigned_to_name) && (
              <p className="text-xs text-on-muted">
                {assignment.holder_kind === "location"
                  ? `${t("assignments.standing_in")}: ${assignment.holder_name}`
                  : `${t("assignments.held_by")}: ${
                      assignment.holder_name ??
                      assignment.partner_name ??
                      assignment.assigned_to_name
                    }`}
              </p>
            )}
        </div>

        <form
          onSubmit={handleSubmit}
          className="min-h-0 flex-1 overflow-y-auto px-5 pb-5 space-y-4 pt-3"
          data-testid="checkin-modal-body"
        >
          <ChoiceGroup
            label={t("assignments.checkin_modal.condition")}
            layout="grid"
            value={condition}
            onChange={(id) => setCondition(id as CheckinCondition)}
            options={checkinConditionOptions(t)}
          />

          {/* Offered where the asset's home is known — the asset page. The
              holder returning from My Assets is not asked where it goes. */}
          {homeLocationId !== undefined && (
            <ReturnLocationField value={returnTo} onChange={setReturnTo} />
          )}

          <Textarea
            label={t("assignments.checkin_modal.notes")}
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            rows={2}
            aria-label={t("assignments.checkin_modal.notes")}
            className="w-full rounded-lg border border-border bg-surface-card text-on px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-accent-500 resize-none placeholder:text-on-muted"
          />

          <SheetActions className="pt-1">
            <Button
              type="button"
              variant="outline"
              onClick={onClose}
              disabled={checkinMutation.isPending}
            >
              {t("common:actions.cancel", "Cancel")}
            </Button>
            <Button type="submit" disabled={checkinMutation.isPending}>
              {checkinMutation.isPending && (
                <Loader2 size={14} className="animate-spin mr-2" />
              )}
              {submitLabel}
            </Button>
          </SheetActions>
        </form>
      </DialogContent>
    </Dialog>
  );
}
