import { documentTitle } from "@/modules/warehouse/lib/documentTitle";
import { memo, useState } from "react";
import * as PopoverPrimitive from "@radix-ui/react-popover";
import {
  ArrowLeftRight,
  ArrowDownToLine,
  ArrowRight,
  ArrowUpFromLine,
  Building2,
  Check,
  CheckCircle,
  Copy,
  MapPin,
  MoreHorizontal,
  PackageMinus,
  PackagePlus,
  Pencil,
  Play,
  RotateCcw,
  Trash2,
  XCircle,
  type LucideIcon,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/Button";
import { Badge } from "@/components/ui/Badge";
import { Card } from "@/components/ui/Card";
import { useCanManage } from "@/hooks/useCanWrite";
import { formatMoney, formatQuantityValue } from "@/utils/formatters";
import { unitLabel } from "@/lib/i18nHelpers";
import { DocumentStatusBadge } from "@/modules/warehouse/components/DocumentStatusBadge";
import { useShowDocumentValue } from "@/modules/warehouse/hooks/useShowDocumentValue";
import type { WarehouseDocumentRow } from "@/modules/warehouse/types";
import type { DocumentColumnContributor } from "@/lib/moduleRegistry";
import {
  toDocumentView,
  type FromModule,
} from "@/modules/warehouse/hooks/useDocumentContributions";

interface DocumentListItemProps {
  doc: WarehouseDocumentRow;
  /** Columns enabled modules add, narrowed by the list to the ones some row
   *  on the page fills. */
  columns?: FromModule<DocumentColumnContributor>[];
  /** The document's own date — the day it is for, else the day it was typed in. */
  formattedDate: string;
  onOpenDetails: (documentId: string) => void;
  onEdit: (doc: WarehouseDocumentRow) => void;
  onRequestAction: (
    type: "confirm" | "cancel" | "delete",
    doc: WarehouseDocumentRow,
  ) => void;
  onDuplicate?: (doc: WarehouseDocumentRow) => void;
  isDuplicatePending?: boolean;
  /** Reopen the picking session this row's badge says is still open; the row
   *  offers it only where that session is a picking one (see
   *  `resumePickingActions`). The page owns the sheet, exactly as it does for
   *  a start from the selection bar. */
  onResumePicking?: (documentId: string) => void;
  /** False leaves the row readable and empties its action menu. */
  canWrite?: boolean;
  isSelected?: boolean;
  /** True while the list has a selection: a tap on the card then toggles it
   *  instead of opening the document, the way the products list behaves once
   *  "Select products" is on. */
  selectionActive?: boolean;
  /** Without it the row has no checkbox: the list does not select. */
  onToggleSelect?: (id: string) => void;
}

function TypeIcon({ type }: { type: WarehouseDocumentRow["type"] }) {
  if (type === "IN")
    return <PackagePlus size={16} className="text-primary-600" />;
  if (type === "OUT")
    return <PackageMinus size={16} className="text-primary-600" />;
  if (type === "INTERNAL_IN")
    return <ArrowDownToLine size={16} className="text-amber-600" />;
  if (type === "INTERNAL_OUT")
    return <ArrowUpFromLine size={16} className="text-violet-600" />;
  if (type === "CORRECTION")
    return <RotateCcw size={16} className="text-orange-500" />;
  return <ArrowLeftRight size={16} className="text-primary-600" />;
}

/**
 * Units done against units planned, one entry per measured unit.
 *
 * CONFIRMED is the live picture. A COMPLETED document speaks only when
 * something did not arrive — a closed receipt printing its plans alone
 * reads as a delivered order, so "planned 3, done 0" has to show where the
 * reader scans; a fully served one stays quiet, a full bar on every
 * completed receipt is decoration. Each unit is compared on its own: an
 * over-receipt in one unit does not cancel a shortage in another, which a
 * comparison of the summed totals let it do. A draft has nothing done yet;
 * its numbers are intentions, so it stays quiet too.
 *
 * The pairs are kept per unit: 20 pcs + 12.5 kg + 30 pack is not
 * "56.5/62.5". The detail page has always shown each line in its own unit.
 */
interface ExecutionUnitProgress {
  unit: string | null;
  done: number;
  planned: number;
}

function buildExecutionProgress(
  doc: WarehouseDocumentRow,
): ExecutionUnitProgress[] | null {
  if (doc.line_count === 0) return null;
  if (doc.status !== "CONFIRMED" && doc.status !== "COMPLETED") return null;
  // Summed per unit by the server, in the order the lines first name them.
  const groups = doc.unit_progress.map((group) => ({
    unit: group.unit,
    planned: Number(group.planned),
    done: Number(group.done),
  }));
  const planned = groups.reduce((sum, group) => sum + group.planned, 0);
  if (planned <= 0) return null;
  // Any group short of its plan means the row speaks; comparing the sums
  // instead let an over-receipt in one unit hide a shortage in another.
  if (
    doc.status === "COMPLETED" &&
    groups.every((group) => group.done >= group.planned)
  ) {
    return null;
  }
  return groups;
}

/**
 * A single-unit document keeps its bar and its pair; a document of several
 * units gets one pair per unit and no bar, because a bar needs one
 * denominator. A line with no unit recorded is a group of its own.
 */
function ExecutionProgress({ groups }: { groups: ExecutionUnitProgress[] }) {
  const { t } = useTranslation("warehouse");

  if (groups.length > 1) {
    const progress = groups
      .map((group) => {
        const pair = `${formatQuantityValue(
          group.done,
        )}/${formatQuantityValue(group.planned)}`;
        const unit = unitLabel(t, group.unit);
        return unit ? `${pair} ${unit}` : pair;
      })
      .join(" · ");
    return (
      <div
        className="mt-1 max-w-[8rem] text-[10px] text-on-muted tabular-nums sm:max-w-none"
        title={t("detail.executionSummaryPerUnit", { progress })}
      >
        {progress}
      </div>
    );
  }

  const single = groups[0];
  if (!single) return null;
  const label = t("detail.executionSummary", {
    done: formatQuantityValue(single.done),
    expected: formatQuantityValue(single.planned),
  });
  return (
    <div className="mt-1 flex items-center justify-end gap-1.5" title={label}>
      <div
        role="meter"
        aria-valuemin={0}
        aria-valuemax={single.planned}
        aria-valuenow={single.done}
        aria-label={label}
        className="h-1 w-10 rounded-full bg-surface-inset overflow-hidden"
      >
        <div
          className="h-full bg-accent-500"
          style={{
            width: `${Math.min(100, Math.round((single.done / single.planned) * 100))}%`,
          }}
        />
      </div>
      <span className="text-[10px] text-on-muted tabular-nums">
        {single.done}/{single.planned}
      </span>
    </div>
  );
}

interface RowAction {
  key: string;
  label: string;
  icon: LucideIcon;
  onClick: () => void;
  danger?: boolean;
  disabled?: boolean;
}

/**
 * The marker of a session still open over the row, beside the status the row
 * always shows: *in progress*, and whose hands it is in. It is derived from
 * the stage the server reads off the session, never from the status — a
 * dispatch whose sheet was closed mid-way is still being picked.
 */
function OpenSessionBadge({ doc }: { doc: WarehouseDocumentRow }) {
  const { t } = useTranslation("warehouse");
  if (doc.work_stage !== "in_progress") return null;
  return (
    <Badge variant="outline">
      {doc.stage_holder_name
        ? t("todo.stageWithHolder", {
            stage: t("todo.stage.in_progress"),
            name: doc.stage_holder_name,
          })
        : t("todo.stage.in_progress")}
    </Badge>
  );
}

/**
 * The types the picking sheet may open over — the same set `#pick` opens
 * the detail page's sheet for, and the single-document picking start behind
 * both accepts them all.
 *
 * The stage below is direction-neutral: a receipt whose receiving session
 * is open reads *in progress* just like a dispatch being picked, while this
 * action always opens the picking sheet, which the server refuses for a
 * type it does not handle ("This session does not handle documents of type
 * IN"). The receipt's own session continues from the document's page, where
 * the notice reads the session's direction; the row keeps its marker here.
 */
const PICKING_SHEET_TYPES = ["OUT", "INT", "INTERNAL_OUT"];

/**
 * The menu's leading action while a session is open over the row: reopening
 * it is the one thing left to do, and it starts nothing new — the server
 * hands back the very session the badge marks. Empty when there is no session
 * open, no callback to open it with, no write permission to act on one, or
 * when the open session is a receiving one the picking sheet cannot resume.
 */
function resumePickingActions(
  doc: WarehouseDocumentRow,
  canWrite: boolean,
  resume: ((documentId: string) => void) | undefined,
  label: string,
): RowAction[] {
  if (!canWrite || !resume || doc.work_stage !== "in_progress") return [];
  if (!PICKING_SHEET_TYPES.includes(doc.type)) return [];
  return [
    {
      key: "resumePicking",
      label,
      icon: Play,
      onClick: () => resume(doc.id),
    },
  ];
}

/**
 * The values modules add to the row, each named, among the row's facts; a
 * column this document has nothing for takes no room.
 */
function ModuleValues({
  doc,
  columns,
}: {
  doc: WarehouseDocumentRow;
  columns?: FromModule<DocumentColumnContributor>[];
}) {
  const { t } = useTranslation();
  if (!columns?.length) return null;
  const view = toDocumentView(doc);
  return (
    <>
      {columns
        .filter((column) => !column.hasValue || column.hasValue(view))
        .map((column) => (
          <span
            key={`${column.moduleName}:${column.key}`}
            className="inline-flex items-baseline gap-1 min-w-0"
          >
            <span>{t(column.label)}</span>
            <span className="truncate text-on">{column.render(view)}</span>
          </span>
        ))}
    </>
  );
}

/**
 * one row implementation for every viewport. The row answers
 * "from whom, where to, for how much" inline (partner, route, value — all
 * already present in the list response), and every action lives behind a
 * single "⋯" overflow menu so the row keeps a stable structure no matter
 * the document status (a DRAFT used to show five icons, PENDING two).
 * Menu markup follows the pattern from PurchaseOrderListItem.
 */
const DocumentListItem = memo(function DocumentListItem({
  doc,
  columns,
  formattedDate,
  onOpenDetails,
  onEdit,
  onRequestAction,
  onDuplicate,
  isDuplicatePending = false,
  onResumePicking,
  canWrite = true,
  isSelected = false,
  selectionActive,
  onToggleSelect,
}: DocumentListItemProps) {
  const { t, i18n } = useTranslation("warehouse");
  const lang = i18n.language?.substring(0, 2) ?? "en";
  // Cancel and delete are the manage-guarded pair; everything else in this
  // menu is a plain write. Both used to be asked of the account's role rather
  // than its permissions, which is a different rule from the one the API
  // applies — and `canWrite` was not asked at all, so a read-only account got
  // Duplicate, Edit, Confirm and Execute and a 403 after each.
  const canManage = useCanManage("warehouse");

  const partnerName = doc.partner_snapshot?.name ?? null;
  const route = [doc.source_location_name, doc.target_location_name].filter(
    Boolean,
  );
  // A row quotes what the document was worth only where the organization
  // tracks value and the document carries a price at all — one question
  // about the amount, answered once.
  const showValue = useShowDocumentValue(doc.type);
  const hasValue = showValue && Boolean(doc.total_gross);
  const linesCount = doc.line_count;
  const execution = buildExecutionProgress(doc);

  const actions: RowAction[] = [
    ...resumePickingActions(doc, canWrite, onResumePicking, t("todo.resume")),
  ];
  if (canWrite && onDuplicate && doc.type !== "CORRECTION") {
    actions.push({
      key: "duplicate",
      label: t("actions.duplicate"),
      icon: Copy,
      onClick: () => onDuplicate(doc),
      disabled: isDuplicatePending,
    });
  }
  if (canWrite && doc.status === "DRAFT" && doc.type === "CORRECTION") {
    actions.push({
      key: "applyCorrection",
      label: t("actions.applyCorrection"),
      icon: Check,
      onClick: () => onOpenDetails(doc.id),
    });
    if (canManage) {
      actions.push({
        key: "delete",
        label: t("actions.delete"),
        icon: Trash2,
        onClick: () => onRequestAction("delete", doc),
        danger: true,
      });
    }
  }
  if (canWrite && doc.status === "DRAFT" && doc.type !== "CORRECTION") {
    actions.push(
      {
        key: "edit",
        label: t("actions.edit"),
        icon: Pencil,
        onClick: () => onEdit(doc),
      },
      {
        key: "confirm",
        label: t("actions.confirm"),
        icon: CheckCircle,
        onClick: () => onRequestAction("confirm", doc),
      },
    );
    if (canManage) {
      actions.push(
        {
          key: "cancel",
          label: t("actions.cancel"),
          icon: XCircle,
          onClick: () => onRequestAction("cancel", doc),
          danger: true,
        },
        {
          key: "delete",
          label: t("actions.delete"),
          icon: Trash2,
          onClick: () => onRequestAction("delete", doc),
          danger: true,
        },
      );
    }
  }
  if (canWrite && doc.status === "CONFIRMED") {
    actions.push({
      key: "execute",
      label: t("actions.execute"),
      icon: Check,
      onClick: () => onOpenDetails(doc.id),
    });
  }

  // The whole card answers a tap through the number button, stretched over
  // it (UI_GUIDELINES §2.3a): it opens the document, or toggles it once a
  // selection is under way. The checkbox and the menu sit above the overlay.
  // The button's press-scale would make it the overlay's containing block
  // for as long as it is held (any transform does, even `scale(1)`), shrinking
  // the overlay under the thumb so the click lands on the card, not the button;
  // `transform: none` while active keeps the overlay card-sized.
  const handleNumberClick = () => {
    if (selectionActive) onToggleSelect?.(doc.id);
    else onOpenDetails(doc.id);
  };

  return (
    <Card className="relative isolate p-3 sm:p-4">
      <div className="flex flex-wrap items-center gap-3 sm:flex-nowrap sm:gap-4">
        {onToggleSelect && (
          // The label is the 44 px target; the input inside stays 16 px.
          <label className="relative z-10 -m-3 flex h-11 w-11 shrink-0 cursor-pointer items-center justify-center sm:m-0 sm:h-auto sm:w-auto">
            <input
              type="checkbox"
              checked={isSelected}
              onChange={() => onToggleSelect?.(doc.id)}
              aria-label={t("bulk.selectAriaLabel", {
                number: documentTitle(t, doc),
              })}
              className="h-4 w-4 shrink-0 rounded border-border text-primary-600 focus:ring-primary-500"
            />
          </label>
        )}
        <div className="shrink-0 w-10 h-10 sm:w-12 sm:h-12 rounded-lg sm:rounded-xl bg-primary-50 flex items-center justify-center">
          <TypeIcon type={doc.type} />
        </div>

        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            {/* break-all — plain truncate cut "ADJUSTMENT/2026/047"
                down to "ADJUSTM…". */}
            <Button
              type="button"
              variant="ghost"
              size="contentSm"
              onClick={handleNumberClick}
              className="min-h-11 items-center px-0 py-0 font-medium after:absolute after:inset-0 cursor-pointer active:![transform:none] sm:min-h-0 text-on break-all text-left justify-start hover:bg-transparent hover:text-primary-600"
            >
              {documentTitle(t, doc)}
            </Button>
            <DocumentStatusBadge status={doc.status} />
            {/* Beside the status: the session still open over this document,
                shown before its start would be refused. */}
            <OpenSessionBadge doc={doc} />
            {doc.is_opening && (
              <span className="text-[10px] font-medium uppercase tracking-wider text-on-secondary bg-surface-raised border border-border rounded px-1.5 py-0.5">
                {t("openingStock.badge")}
              </span>
            )}
          </div>
          <div className="flex items-center gap-x-3 gap-y-0.5 text-xs text-on-secondary mt-0.5 flex-wrap">
            <span className="shrink-0" title={t("fields.documentDate")}>
              {formattedDate}
            </span>
            {partnerName && (
              <span className="inline-flex items-center gap-1 min-w-0">
                <Building2 size={13} className="text-on-muted shrink-0" />
                <span className="truncate">{partnerName}</span>
              </span>
            )}
            {route.length > 0 && (
              <span className="inline-flex items-center gap-1 min-w-0">
                <MapPin size={13} className="text-on-muted shrink-0" />
                <span className="truncate">
                  {doc.source_location_name}
                  {doc.source_location_name && doc.target_location_name && (
                    <ArrowRight
                      size={11}
                      className="inline text-on-muted mx-0.5"
                    />
                  )}
                  {doc.target_location_name}
                </span>
              </span>
            )}
            {doc.external_reference && (
              <span className="truncate">{doc.external_reference}</span>
            )}
            {doc.notes && (
              <span className="truncate max-w-[200px]">{doc.notes}</span>
            )}
            <ModuleValues doc={doc} columns={columns} />
          </div>
        </div>

        {/* Below sm the figures drop under the identity block instead of
            competing with it for the same row: the badge, the meta line and
            the progress bar each need room a phone row cannot give all at
            once. */}
        <div className="shrink-0 text-right max-sm:order-last max-sm:flex max-sm:basis-full max-sm:flex-wrap max-sm:items-baseline max-sm:gap-x-3 max-sm:text-left">
          {hasValue && (
            <div className="text-sm font-semibold text-on tabular-nums">
              {formatMoney(doc.total_gross, doc.currency, lang)}
            </div>
          )}
          <div className="text-xs text-on-secondary">
            {t("fields.linesCount", { count: linesCount })}
          </div>
          {/* how far along a confirmed document is — the row carried
              the number, the status and the value, and said nothing about the
              one thing that changes while the document is open. */}
          {execution && <ExecutionProgress groups={execution} />}
        </div>

        {actions.length > 0 && <RowActionsMenu actions={actions} />}
      </div>
    </Card>
  );
});

/**
 * Single "⋯" overflow menu holding every row action, at every viewport.
 * The trigger never moves and never disappears based on status, so the
 * row's right edge is stable and actions are reachable identically on
 * 390 px and 1440 px.
 */
function RowActionsMenu({ actions }: { actions: RowAction[] }) {
  const { t } = useTranslation("warehouse");
  const [open, setOpen] = useState(false);

  return (
    <PopoverPrimitive.Root open={open} onOpenChange={setOpen}>
      <PopoverPrimitive.Trigger asChild>
        <Button
          variant="ghost"
          size="icon"
          aria-label={t("actions.moreActions")}
          title={t("actions.moreActions")}
          onClick={(e) => e.stopPropagation()}
          className="relative z-10 shrink-0"
        >
          <MoreHorizontal size={18} />
        </Button>
      </PopoverPrimitive.Trigger>
      <PopoverPrimitive.Portal>
        <PopoverPrimitive.Content
          className="z-[var(--z-popover)] w-56 bg-surface-card rounded-xl border border-border shadow-xl p-1 flex flex-col gap-1"
          sideOffset={4}
        >
          {actions.map((action) => (
            <Button
              key={action.key}
              variant="ghost"
              size="sm"
              disabled={action.disabled}
              className={
                action.danger
                  ? "w-full justify-start gap-2 text-red-600"
                  : "w-full justify-start gap-2"
              }
              onClick={(e) => {
                e.stopPropagation();
                setOpen(false);
                action.onClick();
              }}
            >
              <action.icon size={16} />
              {action.label}
            </Button>
          ))}
        </PopoverPrimitive.Content>
      </PopoverPrimitive.Portal>
    </PopoverPrimitive.Root>
  );
}

export { DocumentListItem };
