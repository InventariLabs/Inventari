import { useState } from "react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { itemsApi } from "@/lib/api/items";
import { invalidation } from "@/lib/api/invalidation";
import { useAppMutation } from "@/lib/api/mutationFactory";
import type { Item } from "@/types";
import { formatDate } from "@/utils/formatters";

/** Whether the record is an opened package, by the mark opening writes. */
export function isOpenedRecord(item: Item): boolean {
  const opened = (item.metadata as Record<string, unknown> | null)?.opened;
  return typeof opened === "object" && opened !== null && "at" in opened;
}

/**
 * The use-by of an opened package: the day after which it should not be used,
 * which counts instead of the batch's date when it is earlier. Optional; it
 * can be set, changed or cleared at any time while the package is open.
 */
export default function ItemUseBy({ item }: { item: Item }) {
  const { t } = useTranslation(["items", "common"]);
  const current = item.use_by_date ?? null;
  const [draft, setDraft] = useState(current ?? "");
  const mutation = useAppMutation(
    (useBy: string | null) => itemsApi.setUseBy(item.id, useBy),
    (qc) => invalidation.items(qc),
  );

  return (
    <div className="flex flex-wrap items-end gap-2">
      <Input
        type="date"
        aria-label={t("items:detail.useBy")}
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
      />
      <Button
        size="sm"
        variant="secondary"
        disabled={mutation.isPending || !draft || draft === current}
        onClick={() => mutation.mutate(draft)}
      >
        {t("common:form.save")}
      </Button>
      {current && (
        <Button
          size="sm"
          variant="ghost"
          disabled={mutation.isPending}
          onClick={() => {
            setDraft("");
            mutation.mutate(null);
          }}
        >
          {t("items:detail.useByClear")}
        </Button>
      )}
      {current && (
        <span className="text-xs text-on-muted">{formatDate(current)}</span>
      )}
    </div>
  );
}
