import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { useOrganizationCurrency } from "@/hooks/useOrganizationCurrency";
import { formatQuantityLocalized } from "@/lib/i18nHelpers";
import { formatMoney } from "@/utils/formatters";
import { formatDate, formatDateTime } from "@/utils/helpers";
import { CostGapNote } from "@/modules/maker/components/CostFigure";
import { HoldNote } from "@/modules/maker/components/HoldNote";
import type { BatchRecord } from "@/modules/maker/types/maker";

function Fact({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="min-w-0">
      <dt className="text-xs uppercase tracking-wide text-on-muted print:text-black">
        {label}
      </dt>
      <dd className="text-sm text-on print:text-black break-words">
        {children}
      </dd>
    </div>
  );
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="space-y-2 break-inside-avoid">
      <h3 className="text-sm font-semibold text-on print:text-black border-b border-border print:border-black pb-1">
        {title}
      </h3>
      {children}
    </section>
  );
}

/** The batches the output was filed under, each with how much of it was made, and a batch's hold. */
function OutputBatches({
  batches,
  fallbackName,
  qty,
}: {
  batches: BatchRecord["output_batches"];
  fallbackName: string | null | undefined;
  qty: (value: string | number | null | undefined) => string;
}) {
  const list = batches ?? [];
  return (
    <>
      <span className="font-mono" data-testid="maker-record-batches">
        {list.length > 1
          ? list.map((batch) => (
              <span key={batch.lot_id} className="block">
                {batch.lot_name}
                {batch.quantity != null && ` — ${qty(batch.quantity)}`}
              </span>
            ))
          : list.length > 0
            ? list[0].lot_name
            : (fallbackName ?? "—")}
      </span>
      {list.map((batch) => (
        <HoldNote
          key={batch.lot_id}
          batch={batch}
          className="text-xs text-amber-700 dark:text-amber-400 print:text-black"
        />
      ))}
    </>
  );
}

/**
 * The batch record of a completed run, one page: what was made and in which
 * batch, of what — every ingredient with the batches and quantities taken —
 * what it cost, who planned and who closed it, and what was noted and filed.
 *
 * One column of blocks rather than a wide table, so it reads at phone width;
 * printed, it is black on white on A4.
 */
export function BatchRecordSheet({ record }: { record: BatchRecord }) {
  const { t, i18n } = useTranslation("maker");
  const currency = useOrganizationCurrency();
  const unit = record.output_uom_symbol ?? null;
  const batches = record.output_batches ?? [];
  const uncosted = record.uncosted_ingredients ?? 0;
  const pricedLines = Math.max(
    (record.ingredients ?? []).length - uncosted,
    Number(record.total_cost) > 0 ? 1 : 0,
  );
  const money = (value: string | number | null | undefined) =>
    value === null || value === undefined
      ? "—"
      : formatMoney(value, currency, i18n.language);
  const qty = (value: string | number | null | undefined, symbol = unit) =>
    value === null || value === undefined
      ? "—"
      : formatQuantityLocalized(t, value, symbol);

  return (
    <article
      className="print:block space-y-5 rounded-xl bg-surface-card p-4 sm:p-6 print:bg-white print:p-0 print:text-black"
      data-testid="maker-batch-record"
    >
      <header className="space-y-1">
        <p className="text-xs uppercase tracking-widest text-on-muted print:text-black">
          {t("record.kicker", { number: record.number ?? "—" })}
        </p>
        <h2 className="text-lg font-semibold text-on print:text-black">
          {record.output_template_name ?? "—"}
        </h2>
      </header>

      <dl className="grid grid-cols-2 sm:grid-cols-3 gap-3">
        <Fact label={t("record.recipe")}>{record.recipe_name ?? "—"}</Fact>
        <Fact label={t("record.batch")}>
          <OutputBatches
            batches={batches}
            fallbackName={record.output_lot_name}
            qty={qty}
          />
        </Fact>
        <Fact label={t("batches.card.madeOn")}>
          {record.production_date ? formatDate(record.production_date) : "—"}
        </Fact>
        <Fact label={t("batches.bestBeforeLabel")}>
          {batches.length > 1
            ? batches.map((batch) => (
                <span key={batch.lot_id} className="block">
                  <span className="font-mono">{batch.lot_name}</span>{" "}
                  {batch.best_before ? formatDate(batch.best_before) : "—"}
                </span>
              ))
            : record.best_before
              ? formatDate(record.best_before)
              : "—"}
        </Fact>
        <Fact label={t("record.planned")}>{qty(record.planned_qty)}</Fact>
        <Fact label={t("record.actual")}>{qty(record.actual_qty)}</Fact>
        <Fact label={t("record.location")}>
          {record.output_location_name ?? "—"}
        </Fact>
      </dl>

      <Section title={t("record.ingredients")}>
        <ul className="space-y-3">
          {(record.ingredients ?? []).map((line) => (
            <li key={line.template_id} className="break-inside-avoid">
              <div className="flex flex-wrap items-baseline justify-between gap-x-3">
                <span className="text-sm font-medium text-on print:text-black">
                  {line.template_name ?? "—"}
                </span>
                <span className="text-sm text-on print:text-black tabular-nums">
                  {qty(line.consumed_qty, line.unit)}
                  {line.cost != null && ` · ${money(line.cost)}`}
                </span>
              </div>
              <ul className="mt-1 space-y-0.5 text-xs text-on-secondary print:text-black">
                {(line.batches ?? []).length === 0 ? (
                  <li>{t("record.noBatchTaken")}</li>
                ) : (
                  (line.batches ?? []).map((batch) => (
                    <li key={batch.lot_id ?? "unbatched"}>
                      {t("record.batchLine", {
                        batch: batch.lot_name ?? t("batches.noBatch"),
                        qty: qty(batch.quantity, line.unit),
                        date: batch.expiry_date
                          ? formatDate(batch.expiry_date)
                          : "—",
                      })}
                    </li>
                  ))
                )}
                {line.shortfall_qty != null &&
                  Number(line.shortfall_qty) > 0 && (
                    <li>
                      {t("record.shortfall", {
                        qty: qty(line.shortfall_qty, line.unit),
                      })}
                    </li>
                  )}
              </ul>
            </li>
          ))}
        </ul>
      </Section>

      <Section title={t("record.costs")}>
        <dl className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          <Fact label={t("record.materialCost")}>
            {money(record.material_cost)}
          </Fact>
          <Fact label={t("record.totalCost")}>{money(record.total_cost)}</Fact>
          <Fact label={t("record.estimatedCost")}>
            {money(record.estimated_total_cost)}
          </Fact>
          <Fact label={t("record.unitCost")}>
            {/* No known rate behind the total means none behind the unit
                figure either; a zero would read as free to make. */}
            {uncosted > 0 && pricedLines === 0 ? "—" : money(record.unit_cost)}
          </Fact>
        </dl>
        {(record.ingredients ?? []).some((line) =>
          (line.batches ?? []).some((batch) => batch.lot_id),
        ) && (
          <p className="text-xs text-on-muted print:text-black">
            {t("record.costBasis")}
          </p>
        )}
        <CostGapNote priced={pricedLines} unpriced={uncosted} />
      </Section>

      <Section title={t("record.whoAndWhen")}>
        <dl className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <Fact label={t("record.plannedBy")}>
            {t("record.byAt", {
              who: record.created_by_name ?? "—",
              when: formatDateTime(record.created_at),
            })}
          </Fact>
          <Fact label={t("record.completedBy")}>
            {t("record.byAt", {
              who: record.completed_by_name ?? "—",
              when: record.completed_at
                ? formatDateTime(record.completed_at)
                : "—",
            })}
          </Fact>
        </dl>
      </Section>

      {record.notes && (
        <Section title={t("detail.card.notes")}>
          <p className="text-sm text-on print:text-black whitespace-pre-wrap">
            {record.notes}
          </p>
        </Section>
      )}

      <Section title={t("attachments.title")}>
        {(record.attachments ?? []).length === 0 ? (
          <p className="text-sm text-on-muted print:text-black">
            {t("attachments.empty")}
          </p>
        ) : (
          <ul className="text-sm text-on print:text-black list-disc pl-5">
            {(record.attachments ?? []).map((file) => (
              <li key={file.id}>{file.original_name}</li>
            ))}
          </ul>
        )}
      </Section>
    </article>
  );
}
