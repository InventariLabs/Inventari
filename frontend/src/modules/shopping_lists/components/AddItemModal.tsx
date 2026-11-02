import { useState } from "react";
import { X } from "lucide-react";
import { useTranslation } from "react-i18next";
import { shoppingListsApi } from "@/modules/shopping_lists/api/shopping-lists";
import { QUANTITY_MAX } from "@/modules/shopping_lists/quantityBounds";
import { toast } from "sonner";
import { ShoppingListItemInput } from "@/modules/shopping_lists/types/shopping";

/** The form's own state: the quantity field holds a number the reader typed, or nothing. */
type AddItemDraft = Omit<ShoppingListItemInput, "quantity"> & {
  quantity?: number;
};
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { Sheet } from "@/components/ui/Sheet";
import { UomSelect } from "@/modules/shared/components/UomSelect";
import { extractApiError } from "@/lib/errors";
import {
  QuantityInput,
  quantityStepMessage,
  Textarea,
  useUomPrecision,
} from "@/module-sdk";

interface Props {
  listId: string;
  onClose: () => void;
  onSuccess: () => void;
}

export default function AddItemModal({ listId, onClose, onSuccess }: Props) {
  const { t } = useTranslation(["shopping_lists", "common"]);
  const { t: tCommon } = useTranslation("common");
  const [formData, setFormData] = useState<AddItemDraft>({
    name: "",
    quantity: 1,
    notes: "",
    priority: 0,
  });
  const [submitting, setSubmitting] = useState(false);
  const [touched, setTouched] = useState(false);
  // Asked only once Add is pressed: the unit field sits after the quantity,
  // and naming it missing while the name is still being typed would be a
  // complaint about a field the reader has not reached.
  const [unitMissing, setUnitMissing] = useState(false);
  // The form's floor is the store's step, derived the same way the field
  // beside it derives it: the unit's own step floored at QUANTITY_STEP, and
  // QUANTITY_STEP itself when no unit is chosen yet. A value under it
  // rounds to zero in the column and comes back as a server refusal — and
  // 0.0005, which the store rounds up to 0.001, is not a number the person
  // typed either. The Add button stops offering to send what the field
  // already marks red.
  const precision = useUomPrecision(formData.uom_id);
  const belowFloor =
    quantityStepMessage(formData.quantity ?? "", precision, tCommon) !== "";

  const handleSubmit = async () => {
    setTouched(true);
    // name required, quantity must be positive and within the column's
    // ceiling — the same bounds `app/schemas/validators.py` polices, so a
    // fraction the store holds (half a kilo of flour) goes through and a
    // number the column cannot hold dies as a sentence here, not as a 500.
    if (
      !formData.name.trim() ||
      !formData.quantity ||
      formData.quantity <= 0 ||
      formData.quantity > QUANTITY_MAX ||
      belowFloor
    ) {
      return;
    }
    // "QA Milk 1" with no unit was stored and listed as "1 —": one piece,
    // one pack or one kilogram, the shopper could not tell.
    if (!formData.uom_id) {
      setUnitMissing(true);
      return;
    }

    setSubmitting(true);
    try {
      await shoppingListsApi.addItem(listId, {
        ...formData,
        quantity: Number(formData.quantity),
      });
      onSuccess();
    } catch (err) {
      toast.error(extractApiError(err, t("addItem.addFailed")));
    } finally {
      setSubmitting(false);
    }
  };

  const isNameInvalid = touched && !formData.name.trim();
  const isQtyInvalid =
    touched &&
    (!formData.quantity ||
      formData.quantity <= 0 ||
      formData.quantity > QUANTITY_MAX);

  return (
    <Sheet
      open
      onClose={onClose}
      zIndex="modal-nested"
      aria-label={t("addItem.title")}
    >
      {/* Handle for mobile sheet */}
      <div className="w-12 h-1.5 bg-surface-inset rounded-full mx-auto my-3 sm:hidden" />

      <div className="px-6 pt-2 pb-10 sm:pb-6 flex flex-col flex-1 overflow-hidden">
        <div className="mb-5 flex items-center justify-between">
          <h3 className="text-xl font-semibold text-on">
            {t("addItem.title")}
          </h3>

          <Button
            variant="ghost"
            size="icon"
            onClick={onClose}
            aria-label={t("common:a11y.close")}
          >
            <X size={20} />
          </Button>
        </div>

        <div className="space-y-4 max-h-[70vh] overflow-y-auto pr-1 flex-1">
          <div>
            <label
              htmlFor="item-name"
              className="mb-1.5 block text-xs font-medium uppercase tracking-wider text-on-secondary"
            >
              {t("addItem.nameLabel")}
            </label>

            <Input
              id="item-name"
              type="text"
              value={formData.name}
              onChange={(e) => {
                setFormData({ ...formData, name: e.target.value });
                if (!touched) setTouched(true);
              }}
              placeholder={t("addItem.namePlaceholder")}
              className={
                isNameInvalid ? "border-red-500 bg-red-50 text-red-900" : ""
              }
              error={
                isNameInvalid ? t("addItem.validation.nameRequired") : undefined
              }
              autoFocus
            />
          </div>

          <div className="grid grid-cols-2 items-end gap-4">
            <div>
              {/* The unit decides the step. It is picked in the field beside
                  this one, so until it is, the input stays permissive and
                  tightens the moment a unit is named. */}
              <QuantityInput
                label={t("addItem.quantityLabel")}
                uomId={formData.uom_id}
                max={QUANTITY_MAX}
                value={formData.quantity ?? ""}
                onQuantityChange={(quantity) =>
                  setFormData({
                    ...formData,
                    quantity: quantity ?? undefined,
                  })
                }
                error={
                  isQtyInvalid
                    ? (formData.quantity ?? 0) > QUANTITY_MAX
                      ? t("addItem.validation.quantityMax", {
                          max: QUANTITY_MAX,
                        })
                      : t("addItem.validation.quantityPositive")
                    : undefined
                }
              />
            </div>
            <div>
              <p className="mb-1.5 block text-xs font-medium uppercase tracking-wider text-on-secondary">
                {t("addItem.unitLabel")}
              </p>
              <UomSelect
                value={formData.uom_id ?? null}
                onChange={(_uomId, uom) => {
                  setFormData({ ...formData, uom_id: uom.id });
                  setUnitMissing(false);
                }}
                error={
                  unitMissing ? t("addItem.validation.unitRequired") : undefined
                }
              />
            </div>
          </div>

          <Textarea
            label={t("addItem.noteLabel")}
            value={formData.notes || ""}
            onChange={(e) =>
              setFormData({ ...formData, notes: e.target.value })
            }
            placeholder={t("addItem.notePlaceholder")}
            className="w-full px-4 py-3 border border-border bg-surface rounded-xl font-medium focus:outline-none focus:border-primary-500 focus:bg-surface-card transition-all resize-none"
            rows={2}
          />

          <div className="flex items-center justify-between pt-2 border-t border-border mt-4">
            <span className="text-xs font-medium uppercase tracking-wider text-on-secondary">
              {t("addItem.priorityLabel")}
            </span>
            <div className="flex bg-surface-raised p-1 rounded-lg">
              {[
                { val: 0, label: t("addItem.priority.normal") },
                { val: 2, label: t("addItem.priority.urgent") },
              ].map((p) => (
                <Button
                  key={p.val}
                  type="button"
                  size="sm"
                  variant={formData.priority === p.val ? "secondary" : "ghost"}
                  onClick={() => setFormData({ ...formData, priority: p.val })}
                >
                  {p.label}
                </Button>
              ))}
            </div>
          </div>
        </div>

        <div className="flex items-center justify-end gap-2 mt-8 pb-20 sm:pb-0">
          <Button variant="outline" onClick={onClose}>
            {t("addItem.cancel")}
          </Button>
          <Button
            onClick={handleSubmit}
            disabled={
              submitting || !formData.name.trim() || isQtyInvalid || belowFloor
            }
          >
            {submitting ? t("addItem.adding") : t("addItem.add")}
          </Button>
        </div>
      </div>
    </Sheet>
  );
}
