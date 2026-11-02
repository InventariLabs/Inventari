import { useTranslation } from "react-i18next";
import { Monitor, Pencil, Trash2, Copy } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { EmptyState } from "@/components/ui/EmptyState";
import { useAllCategories } from "@/modules/shared/hooks/useCategories";
import {
  formatModelDisplayName,
  getCategoryLabel,
} from "@/modules/equipment/components/assetUtils";
import type { CategoryDTO } from "@/types";
import type { EquipmentModel } from "@/modules/equipment/api/equipment";

export function ModelGridCard({
  model,
  onEdit,
  onClone,
  onDelete,
  isClonePending,
  isDeletePending,
  readOnly = false,
}: {
  model: EquipmentModel;
  onEdit: (m: EquipmentModel) => void;
  onClone: (m: EquipmentModel) => void;
  onDelete: (m: EquipmentModel) => void;
  isClonePending: boolean;
  isDeletePending: boolean;
  /** True drops the action row — the card stays, as a record to read. */
  readOnly?: boolean;
}) {
  const { t } = useTranslation("equipment");
  // The model carries category_id; its name has to be resolved and then
  // translated, like every other category label in this module. The
  // category_name the API declares is never filled.
  //
  // The name only decorates the card. A list that failed leaves the card
  // without it — true, just less specific — so there is no empty default to
  // mistake for "this model has no category".
  const { data: categories } = useAllCategories();
  const category = categories?.find(
    (c: CategoryDTO) => c.id === model.category_id,
  );

  return (
    <Card className="p-4 flex flex-col" data-testid="model-card">
      {model.image_url && (
        <img
          src={model.image_url}
          alt={model.name}
          loading="lazy"
          className="h-20 w-auto rounded-lg object-cover mb-3"
        />
      )}
      <div className="flex-1">
        {/* Not `brand + name`: most catalogue names already carry the
            brand, and gluing it on again produced "Dell Dell OptiPlex 7010".
            The model picker has resolved this the same way for a while. */}
        <div className="font-medium text-sm text-on">
          {formatModelDisplayName(model)}
        </div>
        {model.description && (
          <p className="text-xs text-on-muted mt-1 line-clamp-2">
            {model.description}
          </p>
        )}
        {category && (
          <span className="inline-block mt-2 text-xs text-on-secondary bg-surface-raised px-2 py-0.5 rounded">
            {getCategoryLabel(t, category)}
          </span>
        )}
      </div>
      {!readOnly && (
        <div className="flex items-center gap-1 mt-3 pt-3 border-t border-border">
          <Button
            variant="ghost"
            size="iconSm"
            onClick={() => onEdit(model)}
            aria-label={t("common:a11y.editNamed", { name: model.name })}
          >
            <Pencil size={14} />
          </Button>
          <Button
            variant="ghost"
            size="iconSm"
            onClick={() => onClone(model)}
            disabled={isClonePending}
            aria-label={t("common:a11y.cloneNamed", { name: model.name })}
          >
            <Copy size={14} />
          </Button>
          <div className="flex-1" />
          <Button
            variant="ghostDanger"
            size="iconSm"
            onClick={() => onDelete(model)}
            disabled={isDeletePending}
            aria-label={t("common:a11y.deleteNamed", { name: model.name })}
          >
            <Trash2 size={14} />
          </Button>
        </div>
      )}
    </Card>
  );
}

export function ModelsEmptyState() {
  const { t } = useTranslation("equipment");

  return (
    <EmptyState
      icon={Monitor}
      title={t("models.empty", "No equipment models yet")}
      description={t(
        "models.empty_hint",
        "Create an asset and use 'Save as model' to create reusable templates",
      )}
    />
  );
}
