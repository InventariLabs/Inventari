import { useState, type KeyboardEvent } from "react";
import { useTranslation } from "react-i18next";
import { ScanLine } from "lucide-react";
import { Input } from "@/components/ui/Input";
import { NativeSelect } from "@/components/ui/NativeSelect";
import { InlineQueryError } from "@/components/ui/QueryResult";
import { formatQuantityLocalized } from "@/lib/i18nHelpers";
import { formatDate } from "@/utils/formatters";
import type { BatchChoice } from "@/modules/maker/hooks/useBatchChoice";
import { findScannedBatch } from "@/modules/maker/lib/batchChoice";
import type { IngredientBatchPlan } from "@/modules/maker/types/maker";

interface IngredientBatchPickerProps {
  choice: BatchChoice;
}

/**
 * Which batch each ingredient is taken from, before the run closes.
 *
 * Each ingredient kept in batches shows the draw the run makes by default —
 * earliest best-before first — and offers every batch with stock free to
 * take; scanning a batch label (or typing its code) picks that batch for the
 * ingredient it belongs to. Ingredients kept without batches are named once,
 * with nothing to choose. A run none of whose ingredients is kept in batches
 * shows nothing here.
 */
export function IngredientBatchPicker({ choice }: IngredientBatchPickerProps) {
  const { t } = useTranslation("maker");
  const [code, setCode] = useState("");
  const [scanMiss, setScanMiss] = useState<string | null>(null);

  if (choice.isError) {
    return (
      <InlineQueryError
        error={choice.error}
        onRetry={() => void choice.refetch()}
      />
    );
  }
  const batched = choice.plans.filter(
    (plan) => (plan.batches ?? []).length > 0,
  );
  const unbatched = choice.plans.filter(
    (plan) => (plan.batches ?? []).length === 0,
  );
  if (batched.length === 0) return null;

  function onScanKey(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key !== "Enter") return;
    event.preventDefault();
    const found = findScannedBatch(batched, code);
    if (found) {
      choice.choose(found.templateId, found.lotId);
      setScanMiss(null);
      setCode("");
    } else {
      setScanMiss(t("batches.scanMiss", { code: code.trim() }));
    }
  }

  return (
    <section
      className="space-y-3"
      aria-labelledby="ingredient-batches-heading"
      data-testid="maker-ingredient-batches"
    >
      <div>
        <h3
          id="ingredient-batches-heading"
          className="text-sm font-semibold text-on"
        >
          {t("batches.heading")}
        </h3>
        <p className="text-xs text-on-muted">{t("batches.hint")}</p>
      </div>
      <Input
        label={t("batches.scanLabel")}
        placeholder={t("batches.scanPlaceholder")}
        leftIcon={<ScanLine size={16} />}
        value={code}
        onChange={(e) => {
          setCode(e.target.value);
          setScanMiss(null);
        }}
        onKeyDown={onScanKey}
        error={scanMiss ?? undefined}
        autoComplete="off"
        data-testid="maker-batch-scan-input"
      />
      {batched.map((plan) => (
        <IngredientBatchRow
          key={plan.template_id}
          plan={plan}
          chosen={choice.choices[plan.template_id] ?? ""}
          short={choice.short.has(plan.template_id)}
          onChoose={(lotId) => choice.choose(plan.template_id, lotId)}
        />
      ))}
      {unbatched.length > 0 && (
        <p className="text-xs text-on-muted">
          {t("batches.notBatched", {
            names: unbatched
              .map((plan) => plan.template_name)
              .filter(Boolean)
              .join(", "),
          })}
        </p>
      )}
    </section>
  );
}

interface IngredientBatchRowProps {
  plan: IngredientBatchPlan;
  chosen: string;
  short: boolean;
  onChoose: (lotId: string) => void;
}

function IngredientBatchRow({
  plan,
  chosen,
  short,
  onChoose,
}: IngredientBatchRowProps) {
  const { t } = useTranslation("maker");
  const unit = plan.uom_symbol ?? null;
  const defaultDraw = (plan.plan ?? [])
    .map(
      (part) =>
        `${part.lot_name ?? t("batches.noBatch")} ${formatQuantityLocalized(
          t,
          part.quantity,
          unit,
        )}`,
    )
    .join(", ");
  return (
    <NativeSelect
      label={t("batches.ingredientLabel", {
        name: plan.template_name ?? "—",
        qty: formatQuantityLocalized(t, plan.needed, unit),
      })}
      value={chosen}
      onChange={(e) => onChoose(e.target.value)}
      error={short ? t("batches.chosenShort") : undefined}
      data-testid={`maker-batch-select-${plan.template_id}`}
    >
      <option value="">
        {t("batches.defaultOrder", { draw: defaultDraw || "—" })}
      </option>
      {(plan.batches ?? []).map((batch) => (
        <option key={batch.lot_id} value={batch.lot_id}>
          {t("batches.option", {
            batch: batch.lot_name,
            date: batch.expiry_date ? formatDate(batch.expiry_date) : "—",
            qty: formatQuantityLocalized(t, batch.available, unit),
          })}
        </option>
      ))}
    </NativeSelect>
  );
}
