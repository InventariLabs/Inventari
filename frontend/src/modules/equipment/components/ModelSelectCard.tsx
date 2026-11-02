import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { Plus } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/Card";
import { NativeSelect } from "@/components/ui/NativeSelect";
import { InlineQueryError } from "@/components/ui/QueryResult";
import { formatModelDisplayName } from "@/modules/equipment/components/assetUtils";
import type { EquipmentModel } from "@/modules/equipment/api/equipment";

interface ModelSelectCardProps {
  models: EquipmentModel[];
  selectedModelId: string;
  onSelect: (models: EquipmentModel[], id: string) => void;
  /**
   * Set when the list never arrived. The model is optional, so the form is
   * still usable — but an empty picker would say there are no models.
   */
  error?: unknown;
  onRetry?: () => void;
}

/**
 * The "prefill from a model" card opening the add-asset form.
 *
 * The card title reads as the field's label for the eye; the control names
 * itself for the tree — a title element cannot point at a select.
 */
export function ModelSelectCard({
  models,
  selectedModelId,
  onSelect,
  error,
  onRetry,
}: ModelSelectCardProps) {
  const { t } = useTranslation("equipment");

  return (
    <Card>
      <CardHeader>
        {/* The create link sits beside the title, not inside it: a link in
            the heading's node glued both into one accessible name — readers
            heard "Select model (optional)Create model" as the heading. */}
        <div className="flex items-center justify-between gap-2">
          <CardTitle className="text-sm">
            {t("models.select_model", "Select model (optional)")}
          </CardTitle>
          <Link
            to="/equipment/templates"
            className="flex shrink-0 items-center gap-1 text-xs text-primary-500 hover:text-primary-600 transition-colors"
          >
            <Plus size={12} />
            {t("models.create", "Create model")}
          </Link>
        </div>
      </CardHeader>
      <CardContent>
        {error ? (
          <InlineQueryError error={error} onRetry={onRetry} />
        ) : (
          <NativeSelect
            value={selectedModelId}
            onChange={(e) => onSelect(models, e.target.value)}
            aria-label={t("models.select_model", "Select model (optional)")}
          >
            <option value="">
              {t("models.no_model", "Create from scratch")}
            </option>
            {models.map((m) => (
              <option key={m.id} value={m.id}>
                {formatModelDisplayName(m)}
              </option>
            ))}
          </NativeSelect>
        )}
      </CardContent>
    </Card>
  );
}
