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
            {candidates.map((item) => (
              <li key={item.id}>
                <Button
                  variant="ghost"
                  className="w-full justify-start gap-3"
                  disabled={assign.isPending}
                  onClick={() => attach(item.id, item.name)}
                >
                  <Package size={16} className="text-on-muted shrink-0" />
                  <span className="truncate">{item.name}</span>
                </Button>
              </li>
            ))}
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
