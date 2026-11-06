import { useParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { Archive } from "lucide-react";
import LoadingSpinner from "@/components/LoadingSpinner";
import { QueryError } from "@/components/ui/QueryResult";
import { RecordNotFound } from "@/components/ui/RecordNotFound";
import { extractApiErrorCode, isNotFoundError } from "@/lib/errors";
import { useItem } from "@/modules/inventory/hooks/useItems";
import ItemDetailContent from "@/modules/inventory/components/items/ItemDetailContent";

/**
 * One product, at an address of its own.
 *
 * `/inventory/items/:id` used to redirect to the list with the action sheet
 * open — a menu of things to do with the record, over a list, with no way to
 * link to it, open it in a second tab, or read the fields it was not asked
 * about. The same physical rack had a page when the Equipment module looked
 * at it and a menu when Inventory did.
 *
 * Overview and History for everyone, and a Movements tab where a module
 * reads the stock ledger: the history lists what happened to the record
 * itself, the ledger lists the stock moves of its product, so the third tab
 * is not the history under a second name and an organization without a
 * module that reads the ledger is not offered it.
 */
export default function ItemDetailPage() {
  const { id } = useParams<{ id: string }>();
  const { t } = useTranslation(["items"]);

  const { data: item, isLoading, isError, error, refetch } = useItem(id ?? "");

  if (isLoading) return <LoadingSpinner />;

  // A product that was deleted and a request that failed are two different
  // answers, and only the second one is worth repeating.
  if (isError && !isNotFoundError(error)) {
    return <QueryError onRetry={() => void refetch()} />;
  }

  if (!item) {
    // "No longer exists" was the answer this screen gave about a record
    // sitting in the archive one click away, Restore under it.
    // The archive-404 carries its own code; the real absence keeps the old
    // sentence.
    if (isError && extractApiErrorCode(error) === "ITEM_ARCHIVED") {
      return (
        <RecordNotFound
          icon={Archive}
          title={t("items:detail.inArchive")}
          description={t("items:detail.inArchiveDesc")}
          backTo="/inventory/items/archived"
          backLabel={t("items:detail.openArchive")}
        />
      );
    }
    return (
      <RecordNotFound
        title={t("items:detail.notFound")}
        backTo="/inventory/items"
        backLabel={t("items:detail.backToList")}
      />
    );
  }

  return <ItemDetailContent item={item} />;
}
