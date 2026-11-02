import {
  Activity,
  AlertTriangle,
  CheckCircle2,
  Clock3,
  Layers,
  MinusCircle,
  Package,
  PlusCircle,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import { Badge } from "@/components/ui/Badge";
import { Card } from "@/components/ui/Card";
import { unitLabel } from "@/lib/i18nHelpers";
import { groupLinesByUnit } from "@/lib/unitQuantities";
import { getDocumentLineStatus } from "@/modules/warehouse/lineStatus";
import { correctionStockSign } from "@/modules/warehouse/types";
import { formatQuantityLocale } from "@/utils/formatters";
import type { TranslateFn } from "@/types/i18n";
import type { WarehouseDocument } from "@/modules/warehouse/types";

interface SummaryTile {
  key: string;
  icon: typeof Clock3;
  iconClassName: string;
  label: string;
  value: string;
}

interface DocumentExecutionSectionProps {
  document: WarehouseDocument;
  isCorrection: boolean;
}

interface UnitQuantities {
  unit: string | null;
  planned: number;
  executed: number;
  added: number;
  removed: number;
}

// Unit counts written in the interface language: at most three decimals,
// and the mark a reader of that language writes.
const formatQuantity = (value: number) =>
  formatQuantityLocale(String(value), 3);

/**
 * Quantities kept per unit, never added across units: 20 pcs + 12.5 kg +
 * 30 pack is not "62.5", and a line with no unit is a group of its own
 * (docs/subsystems/UOM.md — only what shares a measure is added up). The
 * detail page has always shown each line in its own unit.
 */
function buildUnitQuantities(document: WarehouseDocument): UnitQuantities[] {
  // A correction's lines are signed deltas on the document it corrects, and
  // the direction stock moves is that document's: the executor applies
  // delta × correction_sign(original type), so a minus on a dispatch-like
  // original — a scrap, say — puts the goods back on the shelf. Reading the
  // delta's own sign alone named those goods "Removed" on a shelf that had
  // just received them.
  const stockSign = correctionStockSign(document.corrects_document_type);
  return groupLinesByUnit(document.lines, (line) => line.uom?.symbol).map(
    (group) => {
      let planned = 0;
      let executed = 0;
      let added = 0;
      let removed = 0;
      for (const line of group.lines) {
        const linePlanned = Number(
          line.expected_quantity ?? line.quantity ?? 0,
        );
        planned += linePlanned;
        const stockPlanned = stockSign * linePlanned;
        if (stockPlanned > 0) added += stockPlanned;
        if (stockPlanned < 0) removed += Math.abs(stockPlanned);
        const fallbackDoneQuantity =
          document.status === "COMPLETED" ? linePlanned : 0;
        executed += Number(line.done_quantity ?? fallbackDoneQuantity);
      }
      return { unit: group.unit, planned, executed, added, removed };
    },
  );
}

function unitSuffix(t: TranslateFn, unit: string | null): string {
  const label = unitLabel(t, unit);
  return label ? ` ${label}` : "";
}

/** One amount per unit, e.g. "18 pcs. · 12.5 kg". */
function formatAmounts(
  t: TranslateFn,
  groups: UnitQuantities[],
  pick: (group: UnitQuantities) => number,
): string {
  return groups
    .map(
      (group) => `${formatQuantity(pick(group))}${unitSuffix(t, group.unit)}`,
    )
    .join(" · ");
}

/** One executed/planned pair per unit, e.g. "18/20 pcs. · 26/30 pack". */
function formatPairs(t: TranslateFn, groups: UnitQuantities[]): string {
  return groups
    .map(
      (group) =>
        `${formatQuantity(group.executed)}/${formatQuantity(group.planned)}${unitSuffix(t, group.unit)}`,
    )
    .join(" · ");
}

interface SummaryContext {
  isCorrection: boolean;
  isExecutionPhase: boolean;
  singleUnit: boolean;
  doneCount: number;
  executedQuantity: number;
  plannedQuantity: number;
  addedQty: number;
  removedQty: number;
  groups: UnitQuantities[];
}

/**
 * "Done 3 / Planned 7" counted units while the tiles beside it counted
 * lines, so the same card showed 3 and 0 for the same document with nothing
 * saying they measured different things. During execution both counts are
 * named. The quantity half keeps one pair per unit: a catalogue names a
 * quantity, never a common measure for unlike ones.
 */
function buildSummaryText(
  t: TranslateFn,
  document: WarehouseDocument,
  context: SummaryContext,
): string {
  const {
    isCorrection,
    isExecutionPhase,
    singleUnit,
    doneCount,
    executedQuantity,
    plannedQuantity,
    addedQty,
    removedQty,
    groups,
  } = context;
  if (isCorrection) {
    return t("detail.correctionSummary", {
      added: singleUnit
        ? formatQuantity(addedQty)
        : formatAmounts(t, groups, (group) => group.added),
      removed: singleUnit
        ? formatQuantity(removedQty)
        : formatAmounts(t, groups, (group) => group.removed),
    });
  }
  if (isExecutionPhase) {
    return singleUnit
      ? t("detail.executionSummaryDetailed", {
          doneLines: doneCount,
          totalLines: document.lines.length,
          doneUnits: formatQuantity(executedQuantity),
          plannedUnits: formatQuantity(plannedQuantity),
        })
      : t("detail.executionSummaryDetailedPerUnit", {
          doneLines: doneCount,
          totalLines: document.lines.length,
          progress: formatPairs(t, groups),
        });
  }
  return singleUnit
    ? t("detail.executionSummary", {
        done: formatQuantity(executedQuantity),
        expected: formatQuantity(plannedQuantity),
      })
    : t("detail.executionSummaryPerUnit", { progress: formatPairs(t, groups) });
}

export function DocumentExecutionSection({
  document,
  isCorrection,
}: DocumentExecutionSectionProps) {
  const { t } = useTranslation("warehouse");

  const unitQuantities = buildUnitQuantities(document);
  const singleUnit = unitQuantities.length <= 1;
  const plannedQuantity = unitQuantities.reduce(
    (total, group) => total + group.planned,
    0,
  );
  const executedQuantity = unitQuantities.reduce(
    (total, group) => total + group.executed,
    0,
  );
  const addedQty = unitQuantities.reduce(
    (total, group) => total + group.added,
    0,
  );
  const removedQty = unitQuantities.reduce(
    (total, group) => total + group.removed,
    0,
  );

  const lineStatuses = document.lines.map((line) =>
    getDocumentLineStatus(line, document.status),
  );
  const pendingCount = lineStatuses.filter((s) => s === "PENDING").length;
  const partialCount = lineStatuses.filter((s) => s === "PARTIAL").length;
  const exceptionCount = lineStatuses.filter((s) => s === "EXCEPTION").length;
  const doneCount = lineStatuses.filter((s) => s === "DONE").length;
  const remainingCount = pendingCount + partialCount + exceptionCount;
  const needsAttention = remainingCount > 0;

  const isExecutionPhase =
    !isCorrection &&
    (document.status === "CONFIRMED" || document.status === "COMPLETED");

  // A single-unit document keeps one bare figure; several units keep one
  // figure each, because a sum across them is a number in no unit at all.
  const formatAmountValue = (
    total: number,
    pick: (group: UnitQuantities) => number,
  ) =>
    singleUnit ? formatQuantity(total) : formatAmounts(t, unitQuantities, pick);

  const tiles: SummaryTile[] = isCorrection
    ? [
        {
          key: "lines",
          icon: Layers,
          iconClassName: "text-on-muted",
          label: t("detail.snapshotLines"),
          value: String(document.lines.length),
        },
        {
          key: "added",
          icon: PlusCircle,
          iconClassName: "text-accent-600",
          label: t("detail.snapshotDeltaPlus"),
          value: formatAmountValue(addedQty, (group) => group.added),
        },
        {
          key: "removed",
          icon: MinusCircle,
          iconClassName: "text-red-600",
          label: t("detail.snapshotDeltaMinus"),
          value: formatAmountValue(removedQty, (group) => group.removed),
        },
      ]
    : isExecutionPhase
      ? [
          {
            key: "pending",
            icon: Clock3,
            iconClassName: "text-on-muted",
            label: t("detail.lineStatuses.PENDING"),
            value: String(pendingCount),
          },
          {
            key: "partial",
            icon: Activity,
            iconClassName: "text-primary-600",
            label: t("detail.lineStatuses.PARTIAL"),
            value: String(partialCount),
          },
          {
            key: "exception",
            icon: AlertTriangle,
            iconClassName: "text-amber-600",
            label: t("detail.lineStatuses.EXCEPTION"),
            value: String(exceptionCount),
          },
          {
            key: "done",
            icon: CheckCircle2,
            iconClassName: "text-accent-600",
            label: t("detail.lineStatuses.DONE"),
            value: String(doneCount),
          },
        ]
      : [
          {
            key: "lines",
            icon: Layers,
            iconClassName: "text-on-muted",
            label: t("detail.snapshotLines"),
            value: String(document.lines.length),
          },
          {
            key: "planned",
            icon: Package,
            iconClassName: "text-on-muted",
            label: t("detail.snapshotPlanned"),
            value: formatAmountValue(plannedQuantity, (group) => group.planned),
          },
        ];

  const summaryText = buildSummaryText(t, document, {
    isCorrection,
    isExecutionPhase,
    singleUnit,
    doneCount,
    executedQuantity,
    plannedQuantity,
    addedQty,
    removedQty,
    groups: unitQuantities,
  });

  return (
    <Card className="p-4 sm:p-5">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
        <div className="min-w-0 space-y-1.5">
          <div className="flex flex-wrap items-center gap-2">
            <p className="text-[10px] font-medium uppercase tracking-widest text-on-muted">
              {isExecutionPhase
                ? t("detail.summaryTitle")
                : t("detail.snapshotTitle")}
            </p>
            {isExecutionPhase && exceptionCount > 0 && (
              <Badge variant="warning">
                {t("detail.summaryExceptions", { count: exceptionCount })}
              </Badge>
            )}
            {isExecutionPhase && !needsAttention && (
              <Badge variant="success">
                {t("detail.summaryDone", { count: doneCount })}
              </Badge>
            )}
          </div>
          <div className="flex items-center gap-3">
            <p className="text-sm text-on-secondary">{summaryText}</p>
            {/* A bar needs one denominator; several units have none. */}
            {!isCorrection && singleUnit && plannedQuantity > 0 && (
              <div className="h-1.5 w-24 bg-surface-raised rounded-full overflow-hidden border border-border/50">
                <div
                  className="h-full bg-accent-600 transition-all duration-500"
                  style={{
                    width: `${Math.min(100, (executedQuantity / plannedQuantity) * 100)}%`,
                  }}
                />
              </div>
            )}
          </div>
          {/* The instruction strip belongs to the phase where closing is
              a click away. A COMPLETED document's only actions are PDF and
              Duplicate, so "ready to close" here was an instruction with
              no button behind it — and it wore out the sentence that is
              a real instruction one status earlier. */}
          {isExecutionPhase && document.status === "CONFIRMED" && (
            <p className="text-xs text-on-muted">
              {remainingCount === 0
                ? t("detail.summaryReady")
                : t("detail.summaryRemaining", {
                    count: remainingCount,
                    exceptions: exceptionCount,
                  })}
            </p>
          )}
        </div>

        <div
          data-testid="document-operational-snapshot"
          className={`grid shrink-0 grid-cols-2 gap-2 ${
            tiles.length > 2 ? "sm:grid-cols-4" : ""
          }`}
        >
          {tiles.map((tile) => {
            const Icon = tile.icon;
            return (
              <div
                key={tile.key}
                className="rounded-xl border border-border bg-surface-raised/50 px-3 py-2.5"
              >
                <div className="flex items-center gap-1.5">
                  <Icon size={14} className={tile.iconClassName} />
                  <p className="text-[10px] font-medium uppercase tracking-widest text-on-muted">
                    {tile.label}
                  </p>
                </div>
                <p className="mt-1 text-lg font-semibold tracking-tight text-on">
                  {tile.value}
                </p>
              </div>
            );
          })}
        </div>
      </div>
    </Card>
  );
}
