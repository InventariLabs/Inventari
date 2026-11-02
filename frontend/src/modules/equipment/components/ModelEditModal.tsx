import { useEffect, useState } from "react";
import { SheetActions } from "@/components/ui/Sheet";
import { useTranslation } from "react-i18next";
import { Package, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { NativeSelect } from "@/components/ui/NativeSelect";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from "@/components/ui/Dialog";
import { InlineQueryError } from "@/components/ui/QueryResult";
import { useAllCategories } from "@/modules/shared/hooks/useCategories";
import type { EquipmentModel } from "@/modules/equipment/api/equipment";
import type { CategoryDTO } from "@/types";
import { getCategoryLabel } from "@/modules/equipment/components/assetUtils";

// The model dialog used to show raw enum values while the asset
// form next to it showed translated ones. Static keys keep the unused-key
// gate able to see them.
/**
 * A model is a reusable template, so it carries what every unit built from it
 * shares — and nothing that belongs to one unit.
 *
 * Serial number and asset tag were kept out from the start; purchase date,
 * warranty and status stayed and were inherited by every asset created from
 * the model, handing a new laptop somebody else's purchase date and, before
 * the assignment guard, a status claiming it was already deployed. The
 * manufacturer went the same way for a different reason: it is the same fact
 * as the brand, in a second field.
 */
const EMPTY_META: Record<string, string> = {
  model: "",
  group_tag: "",
};

/**
 * Keys a model used to store that describe one unit. Dropped on save so an
 * edited model stops handing them down; reads elsewhere still tolerate them.
 */
const PER_UNIT_KEYS = [
  "purchase_date",
  "warranty_until",
  "equipment_status",
  "manufacturer",
];

interface ModelEditModalProps {
  isOpen: boolean;
  model: EquipmentModel | null;
  isSubmitting: boolean;
  onSave: (data: {
    name: string;
    brand: string;
    description: string;
    category_id: string | null;
    equipment_meta: Record<string, unknown>;
  }) => void;
  onClose: () => void;
}

export default function ModelEditModal({
  isOpen,
  model,
  isSubmitting,
  onSave,
  onClose,
}: ModelEditModalProps) {
  const { t } = useTranslation(["equipment", "common"]);
  const isEdit = Boolean(model);

  const {
    data: allCategories = [],
    error: categoriesError,
    refetch: refetchCategories,
  } = useAllCategories();
  const equipmentCategories = allCategories.filter(
    (c: CategoryDTO) => c.context_tag === "equipment",
  );

  const em = (model?.equipment_meta ?? {}) as Record<string, unknown>;
  const [name, setName] = useState(model?.name ?? "");
  const [brand, setBrand] = useState(model?.brand ?? "");
  const [description, setDescription] = useState(model?.description ?? "");
  const [categoryId, setCategoryId] = useState(model?.category_id ?? "");
  const [meta, setMeta] = useState<Record<string, string>>(
    model
      ? {
          model: String(em.model ?? ""),
          group_tag: String(em.group_tag ?? ""),
        }
      : { ...EMPTY_META },
  );

  // The dialog stays mounted between openings — `isOpen` hides it, it is not
  // unmounted — so its fields kept whatever the last opening left in them.
  // Re-opening the same model then showed the reader their own previous
  // edit, saved or not, instead of what the record says. The fields are
  // seeded from the record each time the dialog opens.
  useEffect(() => {
    if (!isOpen) return;
    const fresh = (model?.equipment_meta ?? {}) as Record<string, unknown>;
    setName(model?.name ?? "");
    setBrand(model?.brand ?? "");
    setDescription(model?.description ?? "");
    setCategoryId(model?.category_id ?? "");
    setMeta(
      model
        ? {
            model: String(fresh.model ?? ""),
            group_tag: String(fresh.group_tag ?? ""),
          }
        : { ...EMPTY_META },
    );
  }, [isOpen, model]);

  if (!isOpen) return null;

  const setMetaField = (key: string, value: string) => {
    setMeta((prev) => ({ ...prev, [key]: value }));
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim()) return;

    const cleanMeta: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(meta)) {
      if (v !== "" && !PER_UNIT_KEYS.includes(k)) cleanMeta[k] = v;
    }

    onSave({
      name: name.trim(),
      brand: brand.trim() || "",
      description: description.trim(),
      category_id: categoryId || null,
      equipment_meta: cleanMeta,
    });
  };

  // ui/Dialog rather than a bespoke z-[100] overlay, so
  // the modal participates in the focus-trap + z-index token system used
  // by the rest of the module.
  return (
    <Dialog open={isOpen} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="w-full max-w-lg mx-0 sm:mx-4 gap-0 p-0 rounded-t-3xl sm:rounded-2xl max-h-[90vh] flex flex-col overflow-hidden">
        <DialogHeader className="p-4 border-b border-border shrink-0">
          <DialogTitle className="flex items-center gap-2">
            <div className="p-2 rounded-lg bg-primary-100 text-primary-700 dark:bg-primary-900/40 dark:text-primary-500">
              <Package size={18} />
            </div>
            {isEdit
              ? t("models.edit", "Edit Model")
              : t("models.create", "Create Model")}
          </DialogTitle>
          <DialogDescription>
            {isEdit
              ? t("models.editSubtitle", "Update saved equipment template.")
              : t(
                  "models.createSubtitle",
                  "Save a reusable template for new assets.",
                )}
          </DialogDescription>
        </DialogHeader>

        <form
          onSubmit={handleSubmit}
          className="p-4 space-y-4 min-h-0 flex-1 overflow-y-auto"
        >
          <div>
            <Input
              label={t("models.name", "Name")}
              required
              value={name}
              onChange={(e) => setName(e.target.value)}
              autoFocus
            />
            {/* Nothing here used to say where the brand goes, so the natural
                thing — typing the full commercial name — put it in twice. */}
            <p className="mt-1 text-xs text-on-muted">{t("models.nameHint")}</p>
          </div>

          <div>
            <Input
              label={t("models.manufacturer", "Manufacturer")}
              value={brand}
              onChange={(e) => setBrand(e.target.value)}
            />
          </div>

          <div>
            <Input
              label={t("models.description", "Description")}
              value={description}
              onChange={(e) => setDescription(e.target.value)}
            />
          </div>

          <div>
            {/* A list that failed must not read as "no category exists". */}
            {categoriesError ? (
              <InlineQueryError
                error={categoriesError}
                onRetry={() => void refetchCategories()}
              />
            ) : (
              <NativeSelect
                label={t("models.category", "Category")}
                id="model-category"
                value={categoryId}
                onChange={(e) => setCategoryId(e.target.value)}
              >
                <option value="">
                  {t("models.noCategory", "No category")}
                </option>
                {equipmentCategories.map((c: CategoryDTO) => (
                  <option key={c.id} value={c.id}>
                    {getCategoryLabel(t, { code: c.code, name: c.name })}
                  </option>
                ))}
              </NativeSelect>
            )}
          </div>

          <hr className="border-border" />
          <p className="text-xs font-medium text-on-muted uppercase tracking-wide">
            {t("models.metadataSection", "Equipment Metadata")}
          </p>

          <div className="grid grid-cols-2 items-end gap-3">
            <div>
              <Input
                label={t("models.model", "Model number")}
                value={meta.model}
                onChange={(e) => setMetaField("model", e.target.value)}
              />
            </div>
            <div>
              <Input
                label={t("models.groupTag", "Group / Kit Tag")}
                value={meta.group_tag}
                onChange={(e) => setMetaField("group_tag", e.target.value)}
              />
            </div>
          </div>

          <p className="text-xs text-on-muted">{t("models.perUnitHint")}</p>

          <SheetActions className="pt-2">
            <Button
              type="button"
              variant="outline"
              onClick={onClose}
              disabled={isSubmitting}
            >
              {t("common:form.cancel", "Cancel")}
            </Button>
            <Button type="submit" disabled={!name.trim() || isSubmitting}>
              {isSubmitting ? (
                <Loader2 size={16} className="animate-spin mr-2" />
              ) : null}
              {isEdit
                ? t("common:actions.save", "Save")
                : t("models.create", "Create")}
            </Button>
          </SheetActions>
        </form>
      </DialogContent>
    </Dialog>
  );
}
