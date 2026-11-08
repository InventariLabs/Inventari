import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import {
  Boxes,
  Camera,
  CheckCheck,
  ClipboardCheck,
  Inbox,
  PackageCheck,
  X,
} from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { EmptyState } from "@/components/ui/EmptyState";
import { QueryError } from "@/components/ui/QueryResult";
import { ReadOnlyNotice } from "@/components/ui/ReadOnlyNotice";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/Tabs";
import LoadingSpinner from "@/components/LoadingSpinner";
import { useCanWrite } from "@/hooks/useCanWrite";
import { useHasPermission } from "@/hooks/useHasPermission";
import { useMediaQuery } from "@/hooks/useMediaQuery";
import { useModulePageHeader } from "@/hooks/useModulePageHeader";
import { useStoragesTree } from "@/hooks/queries/useStoragesTree";
import { useModules } from "@/contexts/ModulesContext";
import { useAuthStore } from "@/store/authStore";
import { ApprovalsQueueBadge } from "@/modules/warehouse/components/ApprovalsQueueBadge";
import { StartActions } from "@/modules/warehouse/components/start/StartActions";
import { TodayActivity } from "@/modules/warehouse/components/start/TodayActivity";
import { WarehouseSelect } from "@/modules/warehouse/components/start/WarehouseSelect";
import { AddTaskForm } from "@/modules/warehouse/components/todo/AddTaskForm";
import { PutawaySheet } from "@/modules/warehouse/components/todo/PutawaySheet";
import { ReplenishSheet } from "@/modules/warehouse/components/todo/ReplenishSheet";
import { QuarantineBlock } from "@/modules/warehouse/components/todo/QuarantineBlock";
import { WorkItemRow } from "@/modules/warehouse/components/todo/WorkItemRow";
import { ListPickingSheet } from "@/modules/warehouse/components/picking/ListPickingSheet";
import {
  MAX_TASKS,
  useDocumentsTodo,
} from "@/modules/warehouse/hooks/useDocumentsTodo";
import {
  useAssignableMembers,
  useAssignWorkItem,
  useDeleteCustomWorkItem,
  useOpenReplenishmentLink,
  useSetCustomWorkItemDone,
  useStartCount,
} from "@/modules/warehouse/hooks/useWorkItems";
import type { TranslateFn } from "@/types/i18n";
import type { WorkItem } from "@/modules/warehouse/types";
import { isPickable } from "@/modules/warehouse/utils/pickable";

/** Tasks read at once; "Show more" asks for another page of them. */
const PAGE_SIZE = 100;

type Filter = "all" | "mine" | "overdue";

/** What an empty filter says; literal keys so the unused-key check sees them. */
function emptyFilterText(t: TranslateFn, filter: Filter): string {
  switch (filter) {
    case "mine":
      return t("todo.filter.empty.mine");
    case "overdue":
      return t("todo.filter.empty.overdue");
    default:
      return t("todo.filter.empty.all");
  }
}

function isPickableTask(item: WorkItem): boolean {
  return (
    item.source_kind === "document" &&
    item.kind !== "approve" &&
    item.next_action !== "request_approval" &&
    isPickable({ type: item.document_type, status: item.document_status })
  );
}

/** The start screen's heading: a greeting on a phone, the question on a desktop. */
function startHeading(
  t: TranslateFn,
  phone: boolean,
  firstName: string | undefined,
): string {
  if (!phone || !firstName) return t("start.title");
  return t("start.phone.greeting", { name: firstName });
}

/** What a phone calls the list it is showing; the desktop names the queue once. */
function phoneTasksTitle(t: TranslateFn, filter: Filter): string {
  switch (filter) {
    case "mine":
      return t("start.phone.tasksTitle");
    case "overdue":
      return t("todo.filter.overdue");
    default:
      return t("start.phone.allTasksTitle");
  }
}

/** The filter the list is showing; a phone opens on the whole floor's work. */
function shownFilter(choice: Filter | null): Filter {
  return choice ?? "all";
}

/** Whether the day holds nothing at all: no task, and no hold to decide. */
function nothingWaiting(
  filter: Filter,
  total: number,
  holds: number | undefined,
): boolean {
  if (filter !== "all") return false;
  return total + (holds ?? 0) === 0;
}

/** Opens the sheet a reorder alert's link names, widening the list to the
 * most the server lists when the task is not among the loaded ones. */
function useReplenishmentSheet(
  tasks: WorkItem[],
  total: number,
  setLimit: (limit: number) => void,
  open: (task: WorkItem) => void,
) {
  const loadAll = useCallback(() => setLimit(MAX_TASKS), [setLimit]);
  useOpenReplenishmentLink(tasks, total, open, loadAll);
}

/**
 * The task card's heading. The desktop names the queue and lets it be
 * narrowed; the phone names the list it is showing and says the order aloud
 * instead of counting a queue.
 */
function TaskListHeader({
  phone,
  filter,
  onFilterChange,
  shown,
  total,
  locationChosen,
}: {
  phone: boolean;
  filter: Filter;
  onFilterChange: (filter: Filter) => void;
  shown: number;
  total: number;
  /** A location narrows documents and put-away, not every kind of task. */
  locationChosen: boolean;
}) {
  const { t } = useTranslation("warehouse");
  return (
    <>
      <div className="flex flex-wrap items-center gap-2 border-b border-border px-4 py-3">
        <h2 className="text-base font-semibold text-on">
          {phone ? phoneTasksTitle(t, filter) : t("todo.title")}
        </h2>
        <span className="text-sm text-on-secondary">
          {phone
            ? t("start.phone.tasksOrder")
            : t("start.todo.count", { shown, total })}
        </span>
        <span className="flex-1" />
        <Tabs
          defaultValue="all"
          value={filter}
          onValueChange={(value) => onFilterChange(value as Filter)}
          panels={false}
        >
          <TabsList aria-label={t("todo.filter.label")}>
            <TabsTrigger value="all" size="sm">
              {t("todo.filter.all")}
            </TabsTrigger>
            <TabsTrigger value="mine" size="sm">
              {t("todo.filter.mine")}
            </TabsTrigger>
            <TabsTrigger value="overdue" size="sm">
              {t("todo.filter.overdue")}
            </TabsTrigger>
          </TabsList>
        </Tabs>
      </div>
      {locationChosen && (
        <p className="border-b border-border px-4 py-2 text-sm text-on-secondary">
          {t("start.warehouse.scopeNote")}
        </p>
      )}
    </>
  );
}

/** Inventory's screens reached from here; their back arrow returns. */
function RelatedScreens({
  isModuleEnabled,
}: {
  isModuleEnabled: (name: string) => boolean;
}) {
  const { t } = useTranslation("warehouse");
  return (
    <nav
      aria-label={t("todo.elsewhere.label")}
      className="flex flex-wrap gap-2"
    >
      <Link
        to="/warehouse/scan"
        className="inline-flex items-center gap-2 rounded-lg border border-border bg-surface-card px-3 py-2 text-sm font-medium text-on-secondary hover:bg-surface-raised"
      >
        <Camera size={16} aria-hidden="true" />
        {t("todo.elsewhere.scan")}
      </Link>
      <Link
        to="/inventory/stock"
        state={{ backTo: "/warehouse/todo" }}
        className="inline-flex items-center gap-2 rounded-lg border border-border bg-surface-card px-3 py-2 text-sm font-medium text-on-secondary hover:bg-surface-raised"
      >
        <Boxes size={16} aria-hidden="true" />
        {t("todo.elsewhere.stock")}
      </Link>
      {isModuleEnabled("stock_takes") && (
        <Link
          to="/inventory/stock-takes"
          state={{ backTo: "/warehouse/todo" }}
          className="inline-flex items-center gap-2 rounded-lg border border-border bg-surface-card px-3 py-2 text-sm font-medium text-on-secondary hover:bg-surface-raised"
        >
          <ClipboardCheck size={16} aria-hidden="true" />
          {t("todo.elsewhere.stockTakes")}
        </Link>
      )}
    </nav>
  );
}

/** The warehouses alone: no branch below them and no number beside them. */
function useWarehouses() {
  // Never a place another module owns (a server rack, a workshop bench): the
  // stock screens leave them out, and a filter by one would show nothing.
  const { data, isError } = useStoragesTree(undefined, {
    excludeModuleContexts: true,
    depth: 1,
    counts: false,
  });
  const warehouses = useMemo(() => data ?? [], [data]);
  return { warehouses, storageTreeFailed: isError };
}

/**
 * The warehouse's start screen: the four things a day is made of, the tasks
 * that came in from the records behind them, and what has already moved
 * today. The actions write their documents in the background, so the screen
 * asks a person what they are doing rather than which document type they
 * want. Each task is one the system read from the record that asks for it —
 * a delivery to receive, an order to ship, production planned, an approval
 * waiting, a count that has fallen due — or one the boss added by hand, with
 * the one button that moves it on. Tasks can be given to a person and
 * filtered to the reader's own or the overdue ones; a phone opens on the whole
 * floor's list and takes an unassigned task for the reader when they tap it.
 * Goods held in quarantine wait below with a way into the screen that decides
 * them. A warehouse selector appears when the organization has more than one,
 * and narrows the day's feed to the shelves under it.
 */
/** Whether the Start screen offers the approvals queue: the module is on and
 * the account holds the right to decide what is in it. */
function useOffersApprovalsQueue(): boolean {
  const { isModuleEnabled } = useModules();
  const canApprove = useHasPermission("approvals:approve");
  return isModuleEnabled("approvals") && canApprove;
}

export default function DocumentsTodoPage() {
  const { t } = useTranslation("warehouse");
  const { setHeader } = useModulePageHeader();
  const canWrite = useCanWrite("warehouse");
  // A batch is released through the stock register, whose write key is the
  // items module's — not the documents grant this page answers to.
  const canWriteItems = useCanWrite("items");
  const { isModuleEnabled } = useModules();
  const navigate = useNavigate();
  // A phone is one person's day rather than the whole floor's queue: a
  // greeting instead of "What are we doing?", and the same filters, opened on
  // everything so that work nobody has taken yet is not invisible. Tapping a
  // task takes it for the reader before its screen opens.
  const isPhone = useMediaQuery("(max-width: 767px)");
  const firstName = useAuthStore(
    (state) => state.user?.full_name?.split(" ")[0],
  );
  const userId = useAuthStore((state) => state.user?.id);
  const [limit, setLimit] = useState(PAGE_SIZE);
  const [filterChoice, setFilterChoice] = useState<Filter | null>(null);
  const filter = shownFilter(filterChoice);
  const { warehouses, storageTreeFailed } = useWarehouses();
  const [warehouseId, setWarehouseId] = useState<string | null>(null);
  const { data, isLoading, isError, refetch } = useDocumentsTodo({
    limit,
    view: filter,
    locationId: warehouseId ?? undefined,
  });
  const { data: members = [], isError: membersFailed } =
    useAssignableMembers(canWrite);
  const assign = useAssignWorkItem();
  const setDone = useSetCustomWorkItemDone();
  const remove = useDeleteCustomWorkItem();
  const startCount = useStartCount();
  const [puttingAway, setPuttingAway] = useState<WorkItem | null>(null);
  const [replenishing, setReplenishing] = useState<WorkItem | null>(null);

  // A phone takes the work the reader taps: an unassigned task is claimed for
  // them before its screen opens, so two people on the floor do not both
  // start the same delivery. The row's assignee is only a hint, and it may be
  // stale, so the claim asks the server for the task only while nobody holds
  // it: losing that claim leaves the task with its holder, says so and opens
  // nothing rather than reassigning somebody else's work. Work already given
  // to somebody is opened as it is — tapping never takes it away from them.
  const take =
    isPhone && canWrite && userId
      ? (task: WorkItem, open: () => void) => {
          if (task.assignee_id) {
            open();
            return;
          }
          assign.mutate(
            {
              sourceKind: task.source_kind,
              sourceId: task.source_id,
              assigneeId: userId,
              onlyIfUnassigned: true,
            },
            { onSuccess: open },
          );
        }
      : undefined;

  // A warehouse is only a choice when the organization keeps more than one;
  // the feed then follows the chosen one's shelves on the server. A failed
  // location tree is said out loud rather than passed off as a single-warehouse
  // organization with nothing to choose.
  //
  // Approvals wait as tasks in the list below; the count beside the link says
  // how many, and the link opens the queue where several can be decided in
  // one pass. Both live in the page header so the list itself stays one thing.
  //
  // The queue lists what waits on *this* account's decision, so it is offered
  // to an account that may approve: the link used to open a page that said
  // "Approving is not something your account can do" — a control that
  // refuses after the click.
  const approvalsEnabled = useOffersApprovalsQueue();
  const headerActions = useMemo(() => {
    const approvals = approvalsEnabled ? (
      <Link
        to="/warehouse/approvals"
        className="inline-flex items-center gap-2 rounded-lg border border-border bg-surface-card px-3 py-1.5 text-sm font-medium text-on-secondary hover:bg-surface-raised"
      >
        <Inbox size={16} aria-hidden="true" />
        {t("navigation.approvalsQueue")}
        <ApprovalsQueueBadge />
      </Link>
    ) : null;
    const warehouse = storageTreeFailed ? (
      <span role="alert" className="text-sm text-on-warning">
        {t("start.warehouse.failed")}
      </span>
    ) : warehouses.length > 1 ? (
      <WarehouseSelect
        warehouses={warehouses}
        value={warehouseId}
        onChange={setWarehouseId}
      />
    ) : null;
    if (!approvals && !warehouse) return undefined;
    return (
      <div className="flex flex-wrap items-center gap-2">
        {approvals}
        {warehouse}
      </div>
    );
  }, [approvalsEnabled, storageTreeFailed, warehouses, warehouseId, t]);

  useEffect(() => {
    setHeader({
      title: startHeading(t, isPhone, firstName),
      subtitle: t("start.subtitle"),
      actions: headerActions,
    });
  }, [setHeader, t, headerActions, isPhone, firstName]);

  // The server has narrowed the list to the filter already.
  const tasks = useMemo(() => data?.work_items.items ?? [], [data]);
  const total = data?.work_items.total ?? 0;
  useReplenishmentSheet(tasks, total, setLimit, setReplenishing);
  const quarantine = data?.decisions.quarantine;

  // Dispatches ticked for one shared session, and the session once started:
  // its ids are fixed at the start so that ticking behind the sheet cannot
  // change what it covers.
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [pickingIds, setPickingIds] = useState<string[] | null>(null);
  const toggleSelect = (id: string) =>
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (!next.delete(id)) next.add(id);
      return next;
    });
  // In the order the list shows them, which is the order the session picks.
  const pickableIds = tasks
    .filter((task) => selectedIds.has(task.source_id) && isPickableTask(task))
    .map((task) => task.source_id);

  // The ticks describe the list in view. A filter change takes rows out of
  // it, and a tick carried off the screen came back ticked the next time the
  // reader widened the list — a selection they had already left behind.
  useEffect(() => {
    setSelectedIds((prev) => {
      if (prev.size === 0) return prev;
      const shown = new Set(tasks.map((task) => task.source_id));
      const next = new Set([...prev].filter((id) => shown.has(id)));
      return next.size === prev.size ? prev : next;
    });
  }, [tasks]);

  // A filter that finds nothing keeps its tabs; only the whole list is "done".
  const empty = nothingWaiting(filter, total, quarantine?.total);

  return (
    <div className="space-y-3 md:space-y-6">
      <ReadOnlyNotice module="warehouse" />
      <StartActions
        onReceive={() => navigate("/warehouse/receive")}
        onIssue={() =>
          navigate("/warehouse/issue", {
            state: { backTo: "/warehouse/todo" },
          })
        }
        onMove={() =>
          navigate("/warehouse/move", {
            state: { backTo: "/warehouse/todo" },
          })
        }
        onCount={() =>
          navigate("/inventory/stock-takes/count", {
            state: { backTo: "/warehouse/todo" },
          })
        }
      />
      {isLoading ? (
        <LoadingSpinner />
      ) : isError ? (
        <QueryError
          message={t("errors.loadDocumentsFailed")}
          onRetry={() => void refetch()}
        />
      ) : (
        <div className="flex flex-wrap items-start gap-3 md:gap-6">
          <section
            className="min-w-0 flex-[999_1_36rem] space-y-3"
            aria-label={t("todo.tasksTitle")}
          >
            {empty ? (
              <EmptyState
                icon={CheckCheck}
                title={t("todo.emptyTitle")}
                description={t("todo.emptySubtitle")}
              />
            ) : (
              <Card className="overflow-hidden p-0">
                <TaskListHeader
                  phone={isPhone}
                  filter={filter}
                  onFilterChange={setFilterChoice}
                  shown={tasks.length}
                  total={total}
                  locationChosen={warehouseId !== null}
                />
                {canWrite && membersFailed && (
                  <p role="alert" className="px-4 pt-3 text-sm text-on-warning">
                    {t("todo.membersFailed")}
                  </p>
                )}
                {tasks.length === 0 ? (
                  <p className="px-4 py-3 text-sm text-on-secondary">
                    {emptyFilterText(t, filter)}
                  </p>
                ) : (
                  <div className="space-y-2 p-2 sm:p-3">
                    {tasks.map((task) => (
                      <WorkItemRow
                        key={task.key}
                        item={task}
                        members={members}
                        canWrite={canWrite}
                        canAssign={!membersFailed}
                        selected={selectedIds.has(task.source_id)}
                        onToggleSelect={
                          canWrite && isPickableTask(task)
                            ? toggleSelect
                            : undefined
                        }
                        onAssign={(row, assigneeId) =>
                          assign.mutate({
                            sourceKind: row.source_kind,
                            sourceId: row.source_id,
                            assigneeId,
                          })
                        }
                        onToggleDone={(row, done) =>
                          setDone.mutate({ id: row.source_id, done })
                        }
                        onDelete={(row) => remove.mutate(row.source_id)}
                        onStartCount={(row) =>
                          startCount.mutate(row.source_id, {
                            onSuccess: (stockTake) =>
                              navigate(
                                `/inventory/stock-takes/${stockTake.id}/counting`,
                              ),
                          })
                        }
                        onPutAway={setPuttingAway}
                        onReplenish={setReplenishing}
                        onTake={take}
                      />
                    ))}
                  </div>
                )}
                {total > tasks.length && (
                  <div className="flex flex-wrap items-center justify-between gap-2 px-4 py-3">
                    <span className="text-sm text-on-secondary">
                      {t("todo.showing", { shown: tasks.length, total })}
                    </span>
                    {limit < MAX_TASKS && (
                      <Button
                        variant="outline"
                        onClick={() =>
                          setLimit(Math.min(limit + PAGE_SIZE, MAX_TASKS))
                        }
                      >
                        {t("todo.showMore")}
                      </Button>
                    )}
                  </div>
                )}
                <p className="border-t border-border px-4 py-3 text-sm text-on-secondary">
                  {t("start.todo.footnote")}
                </p>
              </Card>
            )}
            {canWrite && <AddTaskForm />}
            {quarantine && (
              <QuarantineBlock
                holds={quarantine.items}
                total={quarantine.total}
                canWriteDocuments={canWrite}
                canWriteItems={canWriteItems}
              />
            )}
          </section>
          <TodayActivity
            warehouseId={warehouseId}
            className="flex-[1_1_20rem]"
          />
        </div>
      )}
      <RelatedScreens isModuleEnabled={isModuleEnabled} />
      {canWrite && pickableIds.length > 0 && (
        <div className="sticky bottom-[calc(var(--mobile-nav-height)+env(safe-area-inset-bottom,0px)+0.5rem)] z-[var(--z-sticky)] flex flex-wrap items-center justify-between gap-2 md:bottom-2 rounded-lg border border-primary-200 bg-primary-50/95 px-3 py-2 backdrop-blur dark:border-primary-800 dark:bg-primary-950/80">
          <span className="text-sm font-medium text-primary-900 dark:text-primary-100">
            {t("bulk.selectedCount", { count: pickableIds.length })}
          </span>
          <div className="flex items-center gap-1">
            <Button
              size="sm"
              leftIcon={<PackageCheck size={15} />}
              onClick={() => setPickingIds(pickableIds)}
            >
              {t("bulk.pickSelected", { count: pickableIds.length })}
            </Button>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setSelectedIds(new Set())}
              aria-label={t("bulk.clear")}
            >
              <X size={16} />
            </Button>
          </div>
        </div>
      )}
      {pickingIds && (
        <ListPickingSheet
          documentIds={pickingIds}
          onLeave={() => {
            setPickingIds(null);
            setSelectedIds(new Set());
          }}
        />
      )}
      {puttingAway && (
        <PutawaySheet
          item={puttingAway}
          queue={tasks.filter((task) => task.next_action === "put_away")}
          onClose={() => setPuttingAway(null)}
        />
      )}
      {replenishing && (
        <ReplenishSheet
          item={replenishing}
          onClose={() => setReplenishing(null)}
        />
      )}
    </div>
  );
}
