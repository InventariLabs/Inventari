import { useTranslation } from "react-i18next";
import { TriangleAlert } from "lucide-react";
import { Card } from "@/components/ui/Card";
import { useOrganizationCurrency } from "@/hooks/useOrganizationCurrency";
import { formatMoney } from "@/utils/formatters";
import { formatQuantityLocalized } from "@/lib/i18nHelpers";
import type {
  CostBreakdownEntry,
  PlannedDraw,
  ShortageEntry,
  ProductionOrderLine,
} from "@/modules/maker/types/maker";
import { EmptyState } from "@/components/ui/EmptyState";

interface ProductionIngredientsTableProps {
  lines: ProductionOrderLine[];
  /**
   * What the run would take, for an order that has not consumed anything yet.
   * Resolved from the order's own formula, so it answers the same question
   * completion will ask.
   */
  planned?: CostBreakdownEntry[];
  /**
   * Whether nothing has left stock yet. A draft's empty line list means "not
   * yet", a finished order's means "nothing" — the same table said both.
   */
  isPlanned?: boolean;
  /**
   * The refusal's own list, by template id — the server's answer the banner
   * counts, not a forecast the browser made. Only a draft can have it: the
   * numbers on this list used to stand next to the shortage in silence, and
   * the refusal arrived two clicks later.
   */
  shortages?: Map<string, ShortageEntry>;
  /**
   * The server's count of blocking ingredients — the number completion
   * refuses with. The rows and this count are one verdict; when it is
   * present it decides what the banner says.
   */
  shortageCount?: number | null;
}

interface Row {
  key: string;
  name: string | null;
  id: string;
  qty: string;
  unit: string;
  /** The layer-average rate per unit — "UNIT COST" in both states. */
  unitCost: string | null;
  /** The line's share of the run — "LINE COST" in both states. */
  lineCost: string | null;
  costSource: string | null;
  locationId?: string | null;
  locationName?: string | null;
  /** Draft only: the shelves the run would draw this row from, in draw
   * order — the same plan completion draws by, read before it runs. */
  plannedDraws?: PlannedDraw[];
  /** Closed run recorded after the fact: what the records did not hold. */
  shortfall?: string | null;
}

function fromLine(line: ProductionOrderLine): Row {
  return {
    key: line.id,
    name: line.child_template_name ?? null,
    id: line.child_template_id,
    qty: line.consumed_qty,
    unit: line.unit,
    unitCost: line.unit_cost_snapshot,
    lineCost:
      line.unit_cost_snapshot === null
        ? null
        : String(Number(line.unit_cost_snapshot) * Number(line.consumed_qty)),
    costSource: line.cost_source,
    locationId: line.source_location_id,
    locationName: line.source_location_name,
    shortfall: line.shortfall_qty,
  };
}

function fromEntry(entry: CostBreakdownEntry): Row {
  return {
    key: entry.child_template_id,
    name: entry.child_template_name ?? null,
    id: entry.child_template_id,
    qty: entry.consumed_qty,
    unit: entry.unit,
    unitCost: entry.unit_cost ?? null,
    lineCost: entry.cost ?? null,
    costSource: null,
    plannedDraws: entry.planned_draws,
  };
}

/** Ingredients a production order consumed — or, before it runs, will consume. */
export function ProductionIngredientsTable({
  lines,
  planned,
  isPlanned = false,
  shortages,
  shortageCount,
}: ProductionIngredientsTableProps) {
  const { t, i18n } = useTranslation("maker");
  // A draft is costed off the average of the layers on the shelf; a closed
  // run carries what the layers it drained actually cost. Two different
  // things, two words — and neither is the raw identifier off the wire.
  const costSourceLabel = (source: string) =>
    source === "avco"
      ? t("costSource.avco")
      : source === "fifo"
        ? t("costSource.fifo")
        : source === "none"
          ? t("costSource.none")
          : source;
  const currency = useOrganizationCurrency();

  const rows: Row[] = isPlanned
    ? (planned ?? []).map(fromEntry)
    : lines.map(fromLine);
  const shortCount = shortageCount ?? shortages?.size ?? 0;
  // The consumption a closed run wrote is recorded twice: on the line at
  // numeric(12,4) and in the moves ledger at numeric(12,3). The moves table
  // sits on the same page, so printing the line's fourth decimal read as two
  // numbers for one event with nothing saying which to trust. The ledger is
  // what the reader compares against: this table reads at the move's scale.
  const consumptionRounding = "0.001";
  // The column header's words, under each figure, for the phone's card.
  const phoneLabel =
    "sm:hidden text-[10px] uppercase tracking-widest text-on-muted font-medium";

  return (
    <div className="space-y-3">
      <h2 className="text-xs uppercase tracking-widest text-on-muted font-medium px-1">
        {isPlanned ? t("detail.plannedIngredients") : t("detail.ingredients")}
      </h2>
      {isPlanned && rows.length > 0 && (
        <p className="text-xs text-on-muted px-1">
          {isPlanned && shortCount > 0
            ? t("detail.plannedShortageHint", { count: shortCount })
            : t("detail.plannedIngredientsHint")}
        </p>
      )}
      {rows.length === 0 ? (
        <EmptyState
          variant="compact"
          title={
            isPlanned ? t("detail.emptyLinesPlanned") : t("detail.emptyLines")
          }
        />
      ) : (
        <Card
          className={isPlanned && shortCount > 0 ? "p-2 border-red-200" : "p-2"}
        >
          {/* A phone reads each ingredient as a card: the name on a line of
              its own, the three figures under it with their own labels. Four
              columns on 390 px left the name column one letter wide. */}
          <div className="divide-y divide-border">
            <div className="hidden sm:grid grid-cols-[1fr_auto_auto_auto] gap-4 p-3 text-xs uppercase tracking-widest text-on-muted font-medium">
              <span>{t("detail.line.ingredient")}</span>
              <span className="text-right">{t("detail.line.qty")}</span>
              {/* Both named, in both states: the closed run used to fill
                  "UNIT COST" with the rate while the draft filled it with
                  the line amount — the same header, two meanings two rows
                  of magnitude apart. */}
              <span className="text-right">{t("detail.line.unitCost")}</span>
              <span className="text-right">{t("detail.line.lineCost")}</span>
            </div>
            {rows.map((row) => {
              const short = isPlanned ? shortages?.get(row.id) : undefined;
              return (
                <div
                  key={row.key}
                  className="grid grid-cols-3 gap-x-3 gap-y-1.5 sm:grid-cols-[1fr_auto_auto_auto] sm:gap-4 p-3 items-start sm:items-center text-sm"
                  data-testid="maker-ingredient-row"
                >
                  <div className="col-span-3 sm:col-span-1 min-w-0 break-words font-medium sm:font-normal sm:truncate text-on">
                    {row.name ?? (
                      <span className="font-mono text-xs text-on-muted">
                        {row.id}
                      </span>
                    )}
                  </div>
                  <div className="min-w-0 sm:text-right tabular-nums">
                    <div className={phoneLabel}>{t("detail.line.qty")}</div>
                    <div className="font-medium">
                      {formatQuantityLocalized(
                        t,
                        row.qty,
                        row.unit,
                        consumptionRounding,
                      )}
                    </div>
                    {short && (
                      <div
                        className="text-xs text-red-600 font-medium mt-0.5"
                        data-testid="maker-planned-short"
                      >
                        <TriangleAlert
                          size={11}
                          className="inline mr-1 -mt-0.5"
                        />
                        {short.shortage === null
                          ? t("detail.line.unmeasurableShort")
                          : `${t("detail.line.shortLabel")} ${formatQuantityLocalized(t, short.shortage, short.uom_symbol)}`}
                      </div>
                    )}
                    {row.shortfall && (
                      <div
                        className="text-xs text-on-warning mt-0.5"
                        data-testid="maker-line-shortfall"
                      >
                        {t("detail.line.shortfall", {
                          quantity: formatQuantityLocalized(
                            t,
                            row.shortfall,
                            row.unit,
                            consumptionRounding,
                          ),
                        })}
                      </div>
                    )}
                    {/* The location name, with the id kept in the tooltip for
                        anyone who needs to trace the row. */}
                    {row.locationId && (
                      <div
                        className="text-xs text-on-muted mt-0.5 break-words sm:truncate"
                        title={row.locationId}
                      >
                        ← {row.locationName ?? t("detail.line.unknownLocation")}
                      </div>
                    )}
                    {/* The draft's own forecast of that line: which shelves
                        the run will empty, while closing it is still a
                        choice. Same arrow as the closed run's, so the two
                        tables read as one answered question. */}
                    {row.plannedDraws?.map((draw) => (
                      <div
                        key={draw.location_id}
                        className="text-xs text-on-muted mt-0.5 break-words sm:truncate"
                        title={draw.location_id}
                      >
                        ←{" "}
                        {draw.location_name ?? t("detail.line.unknownLocation")}{" "}
                        · {formatQuantityLocalized(t, draw.quantity, row.unit)}
                      </div>
                    ))}
                  </div>
                  <div className="min-w-0 text-right tabular-nums">
                    <div className={phoneLabel}>
                      {t("detail.line.unitCost")}
                    </div>
                    <div className="font-medium">
                      {row.unitCost === null
                        ? "—"
                        : formatMoney(row.unitCost, currency, i18n.language)}
                    </div>
                    {row.costSource && (
                      <div className="text-xs text-on-muted uppercase tracking-widest mt-0.5">
                        {costSourceLabel(row.costSource)}
                      </div>
                    )}
                  </div>
                  <div className="min-w-0 text-right tabular-nums">
                    <div className={phoneLabel}>
                      {t("detail.line.lineCost")}
                    </div>
                    <div className="font-medium">
                      {row.lineCost === null
                        ? "—"
                        : formatMoney(row.lineCost, currency, i18n.language)}
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        </Card>
      )}
    </div>
  );
}
