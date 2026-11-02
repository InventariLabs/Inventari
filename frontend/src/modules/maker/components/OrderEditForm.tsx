import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { DateInput } from "@/components/ui/DateInput";
import { Card } from "@/components/ui/Card";
import { useUpdateProductionOrder } from "@/modules/maker/hooks/useProduction";

interface OrderEditFormProps {
  orderId: string;
  initial: {
    planned_qty: string;
    production_date: string | null;
    notes: string | null;
  };
  onDone: () => void;
}

/** Inline edit form for a DRAFT production order (planned_qty, date, notes). */
export function OrderEditForm({
  orderId,
  initial,
  onDone,
}: OrderEditFormProps) {
  const { t } = useTranslation("maker");
  const [plannedQty, setPlannedQty] = useState(initial.planned_qty);
  const [productionDate, setProductionDate] = useState(
    initial.production_date ?? "",
  );
  const [notes, setNotes] = useState(initial.notes ?? "");
  const mutation = useUpdateProductionOrder(t("detail.saveFailed"));

  function handleSave(e: React.FormEvent) {
    e.preventDefault();
    mutation.mutate(
      {
        orderId,
        data: {
          planned_qty: plannedQty,
          production_date: productionDate || null,
          notes: notes || null,
        },
      },
      { onSuccess: onDone },
    );
  }

  return (
    <Card className="p-4 space-y-3">
      <form
        onSubmit={handleSave}
        className="space-y-3"
        data-testid="maker-order-edit-form"
      >
        <Input
          label={t("detail.plannedQty")}
          type="number"
          step="any"
          value={plannedQty}
          onChange={(e) => setPlannedQty(e.target.value)}
          data-testid="maker-edit-planned-qty"
        />
        <DateInput
          label={t("detail.productionDate")}
          value={productionDate}
          onChange={(e) => setProductionDate(e)}
          data-testid="maker-edit-production-date"
        />
        <Input
          label={t("detail.notes")}
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          data-testid="maker-edit-notes"
        />
        <div className="flex gap-2">
          <Button
            type="submit"
            disabled={mutation.isPending}
            data-testid="maker-edit-save"
          >
            {t("detail.save")}
          </Button>
          <Button type="button" variant="outline" onClick={onDone}>
            {t("detail.cancelEdit")}
          </Button>
        </div>
      </form>
    </Card>
  );
}
