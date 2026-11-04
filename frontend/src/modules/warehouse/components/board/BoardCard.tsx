import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { MapPin, Trash2 } from "lucide-react";
import { useCanWrite } from "@/hooks/useCanWrite";
import { Badge, type BadgeProps } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Checkbox } from "@/components/ui/Checkbox";
import { NativeSelect } from "@/components/ui/NativeSelect";
import type { TranslateFn } from "@/types/i18n";
import type { WorkItem } from "@/modules/warehouse/types";
import {
  canAct,
  type Member,
} from "@/modules/warehouse/components/todo/WorkItemRow";
import {
  actionLabel,
  workItemNumber,
  workItemSentence,
  workItemTarget,
} from "@/modules/warehouse/components/todo/workItemText";
import { cn } from "@/lib/utils";
import { formatDate, formatTime, todayIso } from "@/utils/formatters";
import { progressPercent } from "./boardColumns";

/** What kind of work the card is, in a word; literal keys for the unused-key
 * check. A kind a module added has no word here and reads as a plain task. */
function kindLabel(t: TranslateFn, item: WorkItem): string {
  switch (item.kind) {
    case "receive":
    case "expected_delivery":
      return t("warehouse:board.kind.receive");
    case "ship":
      return item.document_type === "INT"
        ? t("warehouse:board.kind.transfer")
        : t("warehouse:board.kind.ship");
    case "produce":
      return t("warehouse:board.kind.produce");
    case "approve":
      return t("warehouse:board.kind.approve");
    case "backorder":
      return t("warehouse:board.kind.backorder");
    case "count":
      return t("warehouse:board.kind.count");
    case "replenish":
      return t("warehouse:board.kind.replenish");
    case "custom":
      return t("warehouse:board.kind.custom");
    default:
      return t("warehouse:board.kind.other");
  }
}

function kindVariant(item: WorkItem): BadgeProps["variant"] {
  switch (item.kind) {
    case "receive":
    case "expected_delivery":
      return "info";
    case "ship":
      return "warning";
    case "count":
      return "success";
    case "produce":
      return "secondary";
    default:
      return "outline";
  }
}

function initials(name: string): string {
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((word) => word[0]?.toUpperCase())
    .join("");
}

function WhenText({ item }: { item: WorkItem }) {
  const { t } = useTranslation("warehouse");
  if (item.state === "done") {
    return item.done_at ? <span>{formatTime(item.done_at)}</span> : null;
  }
  if (!item.due_date) return null;
  if (item.overdue) {
    return (
      <span className="font-medium text-on-warning">
        {t("todo.overdue", { date: formatDate(item.due_date) })}
      </span>
    );
  }
  return (
    <span>
      {item.due_date.slice(0, 10) === todayIso()
        ? t("todo.today")
        : formatDate(item.due_date)}
    </span>
  );
}

function Progress({ item }: { item: WorkItem }) {
  const { t } = useTranslation("warehouse");
  const percent = progressPercent(item);
  if (percent === null) return null;
  const label = t("board.card.progress", {
    done: item.lines_done,
    total: Number(item.count),
  });
  return (
    <div className="space-y-1">
      <div
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={percent}
        aria-label={label}
        className="h-1.5 overflow-hidden rounded-full bg-surface-raised"
      >
        <div
          className="h-full rounded-full bg-primary-600"
          style={{ width: `${percent}%` }}
        />
      </div>
      <span className="text-xs text-on-secondary">{label}</span>
    </div>
  );
}

function Whose({ item }: { item: WorkItem }) {
  const { t } = useTranslation("warehouse");
  return (
    <div className="flex items-center gap-2 text-xs text-on-secondary">
      {item.assignee_name ? (
        <>
          <span
            aria-hidden="true"
            className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-primary-50 text-[10px] font-medium text-on"
          >
            {initials(item.assignee_name)}
          </span>
          <span className="truncate">{item.assignee_name}</span>
        </>
      ) : (
        <span>{t("board.people.none")}</span>
      )}
      <span className="flex-1" />
      {item.number && item.kind !== "custom" && (
        <span className="break-all text-on-muted">
          {workItemNumber(t, item)}
        </span>
      )}
    </div>
  );
}

function Where({ item }: { item: WorkItem }) {
  const { t } = useTranslation("warehouse");
  if (!item.place && !item.stage_holder_name) return null;
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-0.5 text-xs text-on-secondary">
      {item.place && (
        <span className="inline-flex min-w-0 items-center gap-1">
          <MapPin size={13} className="shrink-0 text-on-muted" />
          <span className="truncate">{item.place}</span>
        </span>
      )}
      {item.stage_holder_name && (
        <span>
          {t("todo.stageWithHolder", {
            stage: t("todo.stage.in_progress"),
            name: item.stage_holder_name,
          })}
        </span>
      )}
    </div>
  );
}

function Controls({
  item,
  sentence,
  members,
  assignable,
  removable,
  startLabel,
  onAssign,
  onDelete,
  onStartCount,
}: {
  item: WorkItem;
  sentence: string;
  members: Member[];
  assignable: boolean;
  removable: boolean;
  /** The label of the button that begins a due count; none for other cards. */
  startLabel: string | null;
  onAssign: (item: WorkItem, assigneeId: string | null) => void;
  onDelete: (item: WorkItem) => void;
  onStartCount: (item: WorkItem) => void;
}) {
  const { t } = useTranslation("warehouse");
  if (!assignable && !startLabel && !removable) return null;
  return (
    <div className="flex items-center gap-2">
      {assignable && (
        <NativeSelect
          aria-label={t("todo.assignTo", { task: sentence })}
          wrapperClassName="flex-1 min-w-0"
          value={item.assignee_id ?? ""}
          onChange={(e) => onAssign(item, e.target.value || null)}
        >
          <option value="">{t("todo.unassigned")}</option>
          {members.map((member) => (
            <option key={member.id} value={member.id}>
              {member.name}
            </option>
          ))}
        </NativeSelect>
      )}
      {startLabel && (
        <Button size="sm" onClick={() => onStartCount(item)}>
          {startLabel}
        </Button>
      )}
      {removable && (
        <Button
          variant="ghost"
          size="sm"
          aria-label={t("todo.deleteTask", { task: sentence })}
          onClick={() => onDelete(item)}
        >
          <Trash2 size={16} />
        </Button>
      )}
    </div>
  );
}

/**
 * One card of the work board: what kind of work it is, the sentence, when it
 * is due, how far it has got, who has it and the document it came from.
 * It is a view of a work item and keeps nothing of its own. The only things
 * it can change are who has it — by the select, or by being dragged onto a
 * person — and, for a card somebody added by hand, its tick and its removal.
 */
export function BoardCard({
  item,
  members,
  canWrite,
  canAssign,
  dragging,
  onDragStart,
  onDragEnd,
  onAssign,
  onToggleDone,
  onDelete,
  onStartCount,
}: {
  item: WorkItem;
  members: Member[];
  canWrite: boolean;
  /** Whether the people to give a card to were loaded. */
  canAssign: boolean;
  dragging: boolean;
  onDragStart: (item: WorkItem) => void;
  onDragEnd: () => void;
  onAssign: (item: WorkItem, assigneeId: string | null) => void;
  onToggleDone: (item: WorkItem, done: boolean) => void;
  onDelete: (item: WorkItem) => void;
  onStartCount: (item: WorkItem) => void;
}) {
  const { t } = useTranslation("warehouse");
  const canWriteOrders = useCanWrite("purchase_orders");
  const sentence = workItemSentence(t, item);
  const verb = actionLabel(t, item);
  const done = item.state === "done";
  const isCustom = item.kind === "custom";
  const assignable = canWrite && canAssign && !done;
  const startsCount = item.kind === "count" && !item.action_href;
  const showAction = !done && !!verb && canAct(item, canWrite, canWriteOrders);
  const opensRecord = showAction && !startsCount;

  return (
    <article
      draggable={assignable}
      onDragStart={(event) => {
        event.dataTransfer.setData("text/plain", item.key);
        event.dataTransfer.effectAllowed = "move";
        onDragStart(item);
      }}
      onDragEnd={onDragEnd}
      className={cn(
        "flex flex-col gap-2 rounded-xl border bg-surface-card p-3",
        item.overdue && !done ? "border-amber-400" : "border-border",
        assignable && "cursor-grab",
        dragging && "opacity-50",
      )}
    >
      <div className="flex items-center gap-2">
        <Badge variant={kindVariant(item)}>{kindLabel(t, item)}</Badge>
        <span className="flex-1" />
        <span className="text-xs text-on-secondary">
          <WhenText item={item} />
        </span>
      </div>
      <div className="flex items-start gap-2">
        {isCustom && canWrite && (
          <Checkbox
            checked={done}
            onChange={(e) => onToggleDone(item, e.target.checked)}
            aria-label={t("todo.markDone", { task: sentence })}
          />
        )}
        {opensRecord ? (
          <Link
            to={workItemTarget(item)}
            className="text-sm font-semibold break-words text-on hover:underline"
          >
            {sentence}
          </Link>
        ) : (
          <span
            className={cn(
              "text-sm font-semibold break-words",
              done ? "line-through text-on-secondary" : "text-on",
            )}
          >
            {sentence}
          </span>
        )}
      </div>
      <Where item={item} />
      <Progress item={item} />
      <Whose item={item} />
      <Controls
        item={item}
        sentence={sentence}
        members={members}
        assignable={assignable}
        removable={isCustom && canWrite}
        startLabel={startsCount && showAction ? verb : null}
        onAssign={onAssign}
        onDelete={onDelete}
        onStartCount={onStartCount}
      />
    </article>
  );
}
