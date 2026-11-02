import { useState } from "react";
import { SheetActions } from "@/components/ui/Sheet";
import { useTranslation } from "react-i18next";
import { Loader2, PackageCheck } from "lucide-react";
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
  type BulkReturnChoice,
  type CheckinCondition,
} from "@/modules/equipment/components/checkinConditions";
import { ReturnLocationField } from "@/modules/equipment/components/ReturnLocationField";

/** The batch's default destination: every asset to its own location. */
const OWN_PLACE = "own";

interface BulkReturnModalProps {
  selectedCount: number;
  /** How many of the selected assets are actually out on assignment. */
  returnableCount: number;
  isPending: boolean;
  onConfirm: (choice: BulkReturnChoice) => void;
  onClose: () => void;
}

/**
 * One checkin-condition dialog for the whole batch — the leaving employee
 * returns five devices at once, not five dialogs.
 *
 * The dialog counts what it will actually do. It used to promise "Return 2
 * selected assets?" when one of the two was sitting on a shelf, and the shelf
 * one came back as a failure the reader had not asked for.
 */
export function BulkReturnModal({
  selectedCount,
  returnableCount,
  isPending,
  onConfirm,
  onClose,
}: BulkReturnModalProps) {
  const { t } = useTranslation("equipment");
  const skipped = selectedCount - returnableCount;

  const [condition, setCondition] = useState<CheckinCondition>("GOOD");
  const [notes, setNotes] = useState("");
  // The assets may have different homes; by default each goes back to its own.
  const [returnTo, setReturnTo] = useState(OWN_PLACE);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    onConfirm({
      condition,
      notes: notes || undefined,
      returnLocationId: returnTo === OWN_PLACE ? undefined : returnTo,
    });
  };

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent
        className="w-full max-w-md gap-0 p-0 rounded-t-3xl sm:rounded-2xl max-h-[90vh] flex flex-col overflow-hidden"
        data-testid="bulk-return-modal-card"
      >
        <DialogHeader className="flex flex-row items-center gap-3 border-b border-border px-5 py-4">
          <PackageCheck size={18} className="text-primary-500" />
          <DialogTitle className="font-semibold text-on">
            {t("bulk_return.title", { count: returnableCount })}
          </DialogTitle>
          <DialogDescription className="sr-only">
            {t("bulk_return.title", { count: returnableCount })}
          </DialogDescription>
        </DialogHeader>

        <form
          onSubmit={handleSubmit}
          className="min-h-0 flex-1 overflow-y-auto px-5 pb-5 space-y-4 pt-4"
          data-testid="bulk-return-modal-body"
        >
          {skipped > 0 && (
            <p className="text-sm text-on-secondary">
              {t("bulk_return.only_out", {
                count: skipped,
                selected: selectedCount,
              })}
            </p>
          )}

          <ChoiceGroup
            label={t("bulk_return.condition_label")}
            hint={t("bulk_return.condition_hint")}
            layout="grid"
            value={condition}
            onChange={(id) => setCondition(id as CheckinCondition)}
            options={checkinConditionOptions(t)}
          />

          <ReturnLocationField
            value={returnTo}
            onChange={setReturnTo}
            leadingOption={{ id: OWN_PLACE, name: t("bulk_return.own_place") }}
          />

          <Textarea
            label={t("bulk_return.notes_label")}
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            rows={2}
            aria-label={t("bulk_return.notes_label")}
            className="w-full rounded-lg border border-border bg-surface-card text-on px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-accent-500 resize-none placeholder:text-on-muted"
          />

          <SheetActions className="pt-1">
            <Button
              type="button"
              variant="outline"
              onClick={onClose}
              disabled={isPending}
            >
              {t("common:actions.cancel", "Cancel")}
            </Button>
            <Button type="submit" disabled={isPending}>
              {isPending && <Loader2 size={14} className="animate-spin mr-2" />}
              {t("bulk_return.submit")}
            </Button>
          </SheetActions>
        </form>
      </DialogContent>
    </Dialog>
  );
}
