import { useParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { Archive } from "lucide-react";
import LoadingSpinner from "@/components/LoadingSpinner";
import { QueryError } from "@/components/ui/QueryResult";
import { RecordNotFound } from "@/components/ui/RecordNotFound";
import { extractApiErrorCode, isNotFoundError } from "@/lib/errors";
import { useRecordVisit } from "@/module-sdk";
import { useEffect } from "react";
import { useModulePageHeader } from "@/hooks/useModulePageHeader";
import { useItem } from "@/modules/inventory/hooks/useItems";
import ItemDetailContent from "@/modules/inventory/components/items/ItemDetailContent";

/**
 * One product, at an address of its own.
 *
 * `/inventory/items/:id` opens the product's own page, which can be linked to,
 * opened in a second tab, and read field by field. The same physical rack has
 * that page whether the Equipment module or Inventory looks at it.
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
  useRecordVisit("inventory", item);
  const { setHeader } = useModulePageHeader();
  const requestFailed = isError && !isNotFoundError(error);

  // A failed request keeps the page's frame — its name and the way back —
  // so the reader is not left on a bare error with nowhere to go.
  useEffect(() => {
    if (!requestFailed) return;
    setHeader({
      title: t("items:detail.pageTitle"),
      backTo: "/inventory/items",
    });
    return () => setHeader({});
  }, [requestFailed, setHeader, t]);

  if (isLoading) return <LoadingSpinner />;

  // A product that was deleted and a request that failed are two different
  // answers, and only the second one is worth repeating.
  if (requestFailed) {
    return <QueryError error={error} onRetry={() => void refetch()} />;
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
