import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Loader2, Package } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { QueryError } from "@/components/ui/QueryResult";
import {
  Sheet,
  SheetActions,
  SheetBody,
  SheetFooter,
  SheetHeader,
} from "@/components/ui/Sheet";
import { useDebounce } from "@/module-sdk";
import { useItemSearch } from "@/modules/inventory/hooks/useItems";
import { useAssignLabelToItem } from "@/hooks/useAssignLabelToItem";
import { useStorages } from "@/modules/shared/hooks/useStorages";
import { formatQuantityLocalized } from "@/lib/i18nHelpers";
import { formatDate } from "@/utils/formatters";
import { getStorageLocationPath } from "@/utils/helpers";

interface Props {
  /** The free label in the reader's hand. */
  labelCode: string;
  onClose: () => void;
  onAttached: () => void;
}

/**
 * A blank label scanned for a product that is already in the inventory: pick
 * the product and the label becomes its code. Products that carry a label are
 * left out — binding another one would free the first, and a sticker already
 * on the shelf would stop opening anything.
 *
 * A product with stock on several shelves, in several batches or on hold is
 * several rows, and a label names exactly one of them: each row says where it
 * stands, when it expires and how much it holds, so the reader picks the pack
 * in their hand and not the first twin.
 */
export function AttachLabelToItemSheet({
  labelCode,
  onClose,
  onAttached,
}: Props) {
  const { t } = useTranslation(["labels", "common"]);
  const [query, setQuery] = useState("");
  const search = useDebounce(query.trim(), 250);
  const { data, isFetching, isError, refetch } = useItemSearch(search);
  // Only names the place of a row the search already found, so every kind of
  // location is wanted, virtual ones included.
  const { data: storages } = useStorages(undefined, { usage: "all" });
  const assign = useAssignLabelToItem();

  const candidates = (data?.items ?? []).filter((item) => !item.label_code);

  const attach = (itemId: string, name: string) =>
    assign.mutate(
      { shortCode: labelCode, itemId },
      {
        onSuccess: () => {
          toast.success(
            t("labels:attachToItem.success", { code: labelCode, name }),
          );
          onAttached();
        },
      },
    );

  return (
    <Sheet
      open
      onClose={onClose}
      // Opened over the quick-add form, which sits on this tier; the later
      // layer of two equal ones is the one on top.
      zIndex="confirm"
      aria-label={t("labels:attachToItem.title")}
    >
      <SheetHeader title={t("labels:attachToItem.title")} onClose={onClose} />
      <SheetBody className="p-5 space-y-4">
        <p className="text-sm text-on-secondary">
          {t("labels:attachToItem.pickItemHint")}{" "}
          <span className="font-mono font-semibold">{labelCode}</span>
        </p>
        <Input
          autoFocus
          aria-label={t("labels:attachToItem.searchPlaceholder")}
          placeholder={t("labels:attachToItem.searchPlaceholder")}
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        {isError ? (
          <QueryError onRetry={() => void refetch()} />
        ) : isFetching ? (
          <Loader2 className="animate-spin text-on-muted" size={18} />
        ) : search && candidates.length === 0 ? (
          <p className="text-sm text-on-muted">
            {t("labels:attachToItem.noResults")}
          </p>
        ) : (
          <ul className="space-y-1">
            {candidates.map((item) => {
              const place = getStorageLocationPath(
                storages?.find((s) => s.id === item.location_id),
                item.shelf_location,
                undefined,
                storages,
              );
              const expiry = item.effective_expiry_date;
              const details = [
                place,
                expiry
                  ? t("labels:attachToItem.expires", {
                      date: formatDate(expiry),
                    })
                  : "",
                formatQuantityLocalized(t, item.quantity, item.uom?.symbol),
              ].filter(Boolean);
              return (
                <li key={item.id}>
                  <Button
                    variant="ghost"
                    size="content"
                    className="w-full justify-start gap-3 py-2 text-left"
                    disabled={assign.isPending}
                    onClick={() => attach(item.id, item.name)}
                  >
                    <Package size={16} className="text-on-muted shrink-0" />
                    <span className="flex min-w-0 flex-col items-start">
                      <span className="truncate">{item.name}</span>
                      <span className="text-sm text-on-secondary">
                        {details.join(" • ")}
                      </span>
                    </span>
                  </Button>
                </li>
              );
            })}
          </ul>
        )}
      </SheetBody>
      <SheetFooter>
        <SheetActions>
          <Button variant="outline" onClick={onClose}>
            {t("common:actions.cancel")}
          </Button>
        </SheetActions>
      </SheetFooter>
    </Sheet>
  );
}
