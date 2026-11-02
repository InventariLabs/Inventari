import { useState } from "react";
import { useTranslation } from "react-i18next";
import { ListControlBar } from "@/components/ui/ListControlBar";
import LoadingSpinner from "@/components/LoadingSpinner";
import { QueryError } from "@/components/ui/QueryResult";
import { ModelsEmptyState, ModelGridCard } from "./ModelGridCard";
import { formatModelDisplayName } from "./assetUtils";
import type { EquipmentModel } from "@/modules/equipment/api/equipment";

/**
 * The models tab of the templates screen: search bar above the card grid.
 *
 * Search matches what a reader goes on: the label the card shows — the
 * brand glued on where the name lacks it — before the stored name and
 * brand. The catalogue has no server-side search and grows with every
 * import, so the bar is the one way to find anything in it.
 */
export function ModelCatalog({
  models,
  isLoading,
  isError,
  onRetry,
  onEdit,
  onClone,
  onDelete,
  readOnly,
  isClonePending,
  isDeletePending,
}: {
  models: EquipmentModel[];
  isLoading: boolean;
  isError: boolean;
  onRetry: () => void;
  onEdit: (m: EquipmentModel) => void;
  onClone: (m: EquipmentModel) => void;
  onDelete: (m: EquipmentModel) => void;
  readOnly: boolean;
  isClonePending: boolean;
  isDeletePending: boolean;
}) {
  const { t } = useTranslation(["equipment", "common"]);
  const [search, setSearch] = useState("");

  const needle = search.trim().toLowerCase();
  const shown = needle
    ? models.filter((m) =>
        [formatModelDisplayName(m), m.name, m.brand].some((field) =>
          field?.toLowerCase().includes(needle),
        ),
      )
    : models;

  if (isError) return <QueryError onRetry={onRetry} />;
  if (isLoading) return <LoadingSpinner />;
  if (models.length === 0) return <ModelsEmptyState />;

  return (
    <>
      <ListControlBar
        search={{
          value: search,
          onChange: setSearch,
          placeholder: t("common:search"),
        }}
        resultCount={needle ? shown.length : undefined}
      />
      {shown.length === 0 ? (
        <p className="text-sm text-on-muted text-center py-8">
          {t("common:noResults")}
        </p>
      ) : (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {shown.map((m) => (
            <ModelGridCard
              key={m.id}
              model={m}
              onEdit={onEdit}
              onClone={onClone}
              onDelete={onDelete}
              readOnly={readOnly}
              isClonePending={isClonePending}
              isDeletePending={isDeletePending}
            />
          ))}
        </div>
      )}
    </>
  );
}
