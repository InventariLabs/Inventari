import { useEffect, useId, useState } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { Input } from "@/components/ui/Input";
import { useCanManage } from "@/hooks/useCanWrite";
import { extractApiError } from "@/lib/errors";
import { useBomSummary } from "@/modules/maker/hooks/useBom";
import {
  useSetShelfLife,
  useShelfLife,
} from "@/modules/maker/hooks/useBatches";
import { useIsHomeProfile } from "@/modules/maker/hooks/useIsHomeProfile";
import type { Item } from "@/types";

interface ShelfLifeSlotProps {
  data?: { item?: Item };
}

/** A whole number of days from 1, or null for an empty field. */
function parseDays(raw: string): number | null | "invalid" {
  const text = raw.trim();
  if (text === "") return null;
  const days = Number(text);
  return Number.isInteger(days) && days >= 1 && days <= 36500
    ? days
    : "invalid";
}

/**
 * How many days a made product keeps, on its card.
 *
 * A run dates its output batch from it: best before is the run's day plus
 * these days. The value is the maker module's own record, saved when the
 * field is left — the card's Save writes the product's Core fields only.
 * Shown for a product with a formula, or one that already has a shelf life;
 * a product nobody makes has no run to date.
 */
export function ShelfLifeSlot({ data }: ShelfLifeSlotProps) {
  const { t } = useTranslation("maker");
  const id = useId();
  const home = useIsHomeProfile();
  const canManage = useCanManage("maker");
  const templateId = data?.item?.template_id ?? null;
  const { data: summary } = useBomSummary(templateId ?? undefined);
  const { data: saved } = useShelfLife(templateId);
  const save = useSetShelfLife(templateId ?? "");
  const [text, setText] = useState("");
  const savedDays = saved?.shelf_life_days ?? null;
  useEffect(() => {
    setText(savedDays === null ? "" : String(savedDays));
  }, [savedDays]);

  if (!templateId || !saved) return null;
  const made = summary?.items.some(
    (entry) => entry.template_id === templateId && entry.default_recipe_id,
  );
  if (!made && savedDays === null) return null;

  const parsed = parseDays(text);
  const commit = async () => {
    if (parsed === "invalid" || parsed === savedDays) return;
    try {
      await save.mutateAsync(parsed);
      toast.success(t("shelfLife.saved"));
    } catch (error) {
      toast.error(extractApiError(error, t("shelfLife.saveFailed")));
    }
  };

  return (
    <div className="mt-3">
      <Input
        id={id}
        type="number"
        min={1}
        step={1}
        inputMode="numeric"
        label={t("shelfLife.label")}
        description={home ? t("shelfLife.hintHome") : t("shelfLife.hint")}
        suffix={t("shelfLife.days")}
        value={text}
        onChange={(e) => setText(e.target.value)}
        onBlur={() => void commit()}
        error={parsed === "invalid" ? t("shelfLife.invalid") : undefined}
        disabled={!canManage || save.isPending}
        data-testid="maker-shelf-life-input"
      />
    </div>
  );
}

export default ShelfLifeSlot;
