import { Link } from "react-router-dom";
import { Package, Plus } from "lucide-react";
import { TranslateFn } from "@/types/i18n";

interface Props {
  t: TranslateFn;
  storageId: string;
  /** An archived location takes no new products, so it invites none. */
  isArchived?: boolean;
  /** Nor does a reader put one there — `items:write` guards the form. */
  canWriteItems?: boolean;
}

export function StorageItemsEmpty({
  t,
  storageId,
  isArchived,
  canWriteItems = true,
}: Props) {
  return (
    <div className="bg-surface-card rounded-xl p-12 text-center border">
      <Package className="mx-auto text-on-muted mb-4" size={64} />
      <h3 className="text-xl font-medium text-on mb-2">
        {t("locations:detail.empty")}
      </h3>
      <p className="text-on-secondary mb-6">
        {isArchived
          ? t("locations:archived.detailNotice")
          : t("locations:detail.emptySubtitle")}
      </p>
      {!isArchived && canWriteItems && (
        <Link
          to={`/inventory/items/add?location_id=${storageId}`}
          className="inline-flex items-center gap-2 px-6 py-3 bg-primary-700 dark:bg-primary-800 text-white rounded-lg hover:bg-primary-800 dark:hover:bg-primary-900"
        >
          <Plus size={20} />
          {t("items:addProduct")}
        </Link>
      )}
    </div>
  );
}
