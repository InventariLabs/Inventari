import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { MapPin, Trash2, User } from "lucide-react";
import { useCanWrite } from "@/hooks/useCanWrite";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { Checkbox } from "@/components/ui/Checkbox";
import { NativeSelect } from "@/components/ui/NativeSelect";
import type { WorkItem } from "@/modules/warehouse/types";
import { formatDate, todayIso } from "@/utils/formatters";
import { actionLabel, workItemSentence, workItemTarget } from "./workItemText";

export interface Member {
  id: string;
  name: string;
}

/** Whether the account may press the task's button. A document's action
 * and a putaway write to documents; the other screens a task opens check their own grant,
 * and reviewing an approval is open to whoever the queue named. */
export function canAct(
  item: WorkItem,
  canWrite: boolean,
  canWriteOrders: boolean,
): boolean {
  if (!item.next_action && !item.action_href) return false;
  // Putting away posts a move, which is a write to documents.
  if (item.source_kind === "putaway") return canWrite;
  // Filling a pick face from reserve is a transfer too, and the proposal
  // and the move are the orders module's routes.
  if (item.source_kind === "replenishment") return canWrite && canWriteOrders;
  if (item.source_kind !== "document") return true;
  return item.next_action === "review_approval" || canWrite;
}

function DueText({ item }: { item: WorkItem }) {
  const { t } = useTranslation("warehouse");
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

/** Whether the stock a backorder waits for is on the shelves, as the server read it. */
function StockCoverBadge({ cover }: { cover: WorkItem["stock_cover"] }) {
  const { t } = useTranslation("warehouse");
  switch (cover) {
    case "full":
      return <Badge variant="success">{t("todo.stockCover.full")}</Badge>;
    case "partial":
      return <Badge variant="warning">{t("todo.stockCover.partial")}</Badge>;
    case "none":
      return <Badge variant="outline">{t("todo.stockCover.none")}</Badge>;
    default:
      return null;
  }
}

/**
 * One task: the sentence, when it is due, who it is for, and the one button
 * that moves it on. Everything on it is read from the server's task; the row
 * keeps no state of its own.
 */
export function WorkItemRow({
  item,
  members,
  canWrite,
  canAssign,
  selected,
  onToggleSelect,
  onAssign,
  onToggleDone,
  onDelete,
  onStartCount,
  onPutAway,
  onReplenish,
  onTake,
}: {
  item: WorkItem;
  members: Member[];
  canWrite: boolean;
  /** Whether the people to give a task to were loaded. */
  canAssign: boolean;
  /** Present only where this task can be ticked for a shared picking session. */
  selected?: boolean;
  onToggleSelect?: (id: string) => void;
  onAssign: (item: WorkItem, assigneeId: string | null) => void;
  onToggleDone: (item: WorkItem, done: boolean) => void;
  onDelete: (item: WorkItem) => void;
  /** Begins a due count, which has no screen of its own to open yet. */
  onStartCount: (item: WorkItem) => void;
  /** Puts away goods waiting in a receiving area, on the page itself. */
  onPutAway: (item: WorkItem) => void;
  /** Fills a pick face from reserve, on the page itself. */
  onReplenish: (item: WorkItem) => void;
  /**
   * On a phone, opens the task after taking it for the reader. Left out on a
   * desktop, where a task is opened without changing who it is for. Where it
   * is set, the row shows who holds the task and leaves the choosing of a
   * person to the desktop: a tap is the whole gesture.
   */
  onTake?: (item: WorkItem, open: () => void) => void;
}) {
  const { t } = useTranslation("warehouse");
  const navigate = useNavigate();
  const canWriteOrders = useCanWrite("purchase_orders");
  const sentence = workItemSentence(t, item);
  const verb = actionLabel(t, item);
  const isCustom = item.kind === "custom";
  const done = item.state === "done";
  const startsCount = item.kind === "count" && !item.action_href;
  const putsAway = item.next_action === "put_away";
  const replenishes = item.next_action === "replenish";
  const open = () => {
    if (startsCount) onStartCount(item);
    else if (putsAway) onPutAway(item);
    else if (replenishes) onReplenish(item);
    else navigate(workItemTarget(item));
  };

  return (
    <Card className="p-3 sm:p-4" data-testid="work-item">
      <div className="flex flex-wrap items-center gap-3">
        {isCustom && canWrite && (
          <Checkbox
            checked={done}
            onChange={(e) => onToggleDone(item, e.target.checked)}
            aria-label={t("todo.markDone", { task: sentence })}
          />
        )}
        {onToggleSelect && (
          // The label is the 44 px target; the box inside stays 16 px.
          <label className="-m-3 flex h-11 w-11 shrink-0 cursor-pointer items-center justify-center sm:m-0 sm:h-auto sm:w-auto">
            <input
              type="checkbox"
              checked={!!selected}
              onChange={() => onToggleSelect(item.source_id)}
              aria-label={t("bulk.selectAriaLabel", { number: item.number })}
              className="h-4 w-4 shrink-0 cursor-pointer rounded border-border text-primary-600 focus:ring-primary-500"
            />
          </label>
        )}
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span
              className={`font-medium break-words ${done ? "line-through text-on-secondary" : "text-on"}`}
            >
              {sentence}
            </span>
            <StockCoverBadge cover={item.stock_cover} />
            {item.state === "in_progress" && (
              <Badge variant="outline">
                {item.stage_holder_name
                  ? t("todo.stageWithHolder", {
                      stage: t("todo.stage.in_progress"),
                      name: item.stage_holder_name,
                    })
                  : t("todo.stage.in_progress")}
              </Badge>
            )}
          </div>
          <div className="flex items-center gap-x-3 gap-y-0.5 text-xs text-on-secondary mt-0.5 flex-wrap">
            <DueText item={item} />
            {item.number && !isCustom && (
              <span className="break-all">{item.number}</span>
            )}
            {item.place && (
              <span className="inline-flex items-center gap-1 min-w-0">
                <MapPin size={13} className="text-on-muted shrink-0" />
                <span className="truncate">{item.place}</span>
              </span>
            )}
            {(!canWrite || onTake) && item.assignee_name && (
              <span className="inline-flex items-center gap-1 min-w-0">
                <User size={13} className="text-on-muted shrink-0" />
                <span className="truncate">{item.assignee_name}</span>
              </span>
            )}
          </div>
        </div>
        {canWrite && canAssign && !done && !onTake && (
          <NativeSelect
            aria-label={t("todo.assignTo", { task: sentence })}
            wrapperClassName="w-full sm:w-44 sm:shrink-0"
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
        {!done && verb && canAct(item, canWrite, canWriteOrders) && (
          <Button
            className="max-sm:w-full"
            onClick={() =>
              onTake && !item.assignee_id ? onTake(item, open) : open()
            }
          >
            {verb}
          </Button>
        )}
        {isCustom && canWrite && (
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
    </Card>
  );
}
