import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Loader2 } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/Button";
import {
  Sheet,
  SheetActions,
  SheetBody,
  SheetFooter,
  SheetHeader,
} from "@/components/ui/Sheet";
import { LabelPickerInput } from "@/modules/shared/components/LabelPickerInput";
import { useAssignLabelToItem } from "@/hooks/useAssignLabelToItem";

interface Props {
  item: { id: string; name: string };
  onClose: () => void;
  onAttached: () => void;
}

/**
 * A product already in the inventory, a sticker already on the shelf: pick
 * the free label from the pool (or make one) and it becomes the product's
 * code — the same binding a scan makes for a new product.
 */
export function AttachLabelToExistingItemSheet({
  item,
  onClose,
  onAttached,
}: Props) {
  const { t } = useTranslation(["labels", "common"]);
  const [code, setCode] = useState("");
  const assign = useAssignLabelToItem();

  const submit = () =>
    assign.mutate(
      { shortCode: code, itemId: item.id },
      {
        onSuccess: () => {
          toast.success(
            t("labels:attachToItem.success", { code, name: item.name }),
          );
          onAttached();
        },
      },
    );

  return (
    <Sheet
      open
      onClose={onClose}
      aria-label={t("labels:attachToItem.itemAction")}
    >
      <SheetHeader
        title={t("labels:attachToItem.itemAction")}
        onClose={onClose}
      />
      {/* The picker's list opens downward over the body; without room under
          it the body's own scroll cuts the list off. */}
      <SheetBody className="p-5 space-y-3 min-h-80">
        <p className="text-sm text-on-secondary">
          {t("labels:attachToItem.pickLabelHint", { name: item.name })}
        </p>
        <LabelPickerInput value={code} onChange={setCode} />
      </SheetBody>
      <SheetFooter>
        <SheetActions>
          <Button variant="outline" onClick={onClose}>
            {t("common:actions.cancel")}
          </Button>
          <Button onClick={submit} disabled={!code || assign.isPending}>
            {assign.isPending && <Loader2 size={16} className="animate-spin" />}
            {t("labels:attachToItem.submit")}
          </Button>
        </SheetActions>
      </SheetFooter>
    </Sheet>
  );
}
