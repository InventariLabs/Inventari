import { useEffect, useMemo, useState } from "react";
import { Navigate, useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { Plus } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { QueryError } from "@/components/ui/QueryResult";
import { ReadOnlyNotice } from "@/components/ui/ReadOnlyNotice";
import LoadingSpinner from "@/components/LoadingSpinner";
import { useCanWrite } from "@/hooks/useCanWrite";
import { useMediaQuery } from "@/hooks/useMediaQuery";
import { useModulePageHeader } from "@/hooks/useModulePageHeader";
import { BoardCard } from "@/modules/warehouse/components/board/BoardCard";
import { BoardMeasures } from "@/modules/warehouse/components/board/BoardMeasures";
import {
  BoardPeople,
  type BoardPerson,
} from "@/modules/warehouse/components/board/BoardPeople";
import {
  ALL_PEOPLE,
  COLUMN_STATES,
  assigneeParam,
  startOfDayIso,
  type ColumnState,
  type PersonFilter,
} from "@/modules/warehouse/components/board/boardColumns";
import { AddTaskForm } from "@/modules/warehouse/components/todo/AddTaskForm";
import {
  MAX_TASKS,
  useDocumentsTodo,
} from "@/modules/warehouse/hooks/useDocumentsTodo";
import {
  useAssignableMembers,
  useAssignWorkItem,
  useDeleteCustomWorkItem,
  useSetCustomWorkItemDone,
  useStartCount,
  useWorkMeasures,
} from "@/modules/warehouse/hooks/useWorkItems";
import type { TranslateFn } from "@/types/i18n";
import type { WorkItem } from "@/modules/warehouse/types";

/** Cards of a column read at once; "Show more" asks for another page of them. */
const PAGE_SIZE = 100;

/** A screen left open follows the events behind its cards. */
const REFRESH_MS = 30_000;

/** Literal keys so the unused-key check sees every column title. */
function columnTitle(t: TranslateFn, state: ColumnState): string {
  switch (state) {
    case "todo":
      return t("board.columns.todo");
    case "in_progress":
      return t("board.columns.in_progress");
    default:
      return t("board.columns.done");
  }
}

/** What a column says when it holds more cards than it shows. */
function MoreCards({
  shown,
  total,
  limit,
  onMore,
}: {
  shown: number;
  total: number;
  limit: number;
  onMore: () => void;
}) {
  const { t } = useTranslation("warehouse");
  if (total <= shown) return null;
  return (
    <div className="flex flex-wrap items-center gap-2 px-1">
      <span className="text-sm text-on-secondary">
        {t("board.truncated", { shown, total })}
      </span>
      {limit < MAX_TASKS && (
        <Button type="button" variant="outline" size="sm" onClick={onMore}>
          {t("todo.showMore")}
        </Button>
      )}
    </div>
  );
}

/**
 * The work board: the same work items as Start, laid out by what has happened
 * to them. A card is in the column its state says and moves only when the
 * record behind it changes — a session starts, a document is posted — so the
 * columns accept no drops. The two things done by hand are giving a card to a
 * person (drag it onto their chip, or use the select on the card) and the
 * cards a person adds themselves. A phone shows today's work on Start
 * instead.
 */
export default function DocumentsBoardPage() {
  const { t } = useTranslation("warehouse");
  const { setHeader } = useModulePageHeader();
  const navigate = useNavigate();
  const canWrite = useCanWrite("warehouse");
  const isPhone = useMediaQuery("(max-width: 767px)");
  const [person, setPerson] = useState<PersonFilter>(ALL_PEOPLE);
  const [adding, setAdding] = useState(false);
  const [dragged, setDragged] = useState<WorkItem | null>(null);
  const [limits, setLimits] = useState<Record<ColumnState, number>>({
    todo: PAGE_SIZE,
    in_progress: PAGE_SIZE,
    done: PAGE_SIZE,
  });

  // Each column asks the server for its own cards, so a person's filter, a
  // column's count and "today" are worked out over everything there is and
  // not over the first page of it.
  const assignee = assigneeParam(person);
  // A string, so it is the same value all day and the query key holds still.
  const doneSince = startOfDayIso(new Date());
  const asked = { assignee, refetchInterval: REFRESH_MS };
  const queries = {
    todo: useDocumentsTodo({ ...asked, state: "todo", limit: limits.todo }),
    in_progress: useDocumentsTodo({
      ...asked,
      state: "in_progress",
      limit: limits.in_progress,
    }),
    done: useDocumentsTodo({
      ...asked,
      state: "done",
      limit: limits.done,
      doneSince,
    }),
  };
  const { data: late, isError: lateFailed } = useDocumentsTodo({
    view: "overdue",
    limit: 1,
    refetchInterval: REFRESH_MS,
  });
  const isLoading = COLUMN_STATES.some((state) => queries[state].isLoading);
  const isError = COLUMN_STATES.some((state) => queries[state].isError);
  const refetch = () =>
    Promise.all(COLUMN_STATES.map((state) => queries[state].refetch()));
  const measures = useWorkMeasures(REFRESH_MS);
  const { data: members = [], isError: membersFailed } =
    useAssignableMembers(canWrite);
  const assign = useAssignWorkItem();
  const setDone = useSetCustomWorkItemDone();
  const remove = useDeleteCustomWorkItem();
  const startCount = useStartCount();

  useEffect(() => {
    setHeader({ title: t("board.title"), subtitle: t("board.subtitle") });
  }, [setHeader, t]);

  const todoData = queries.todo.data;
  const progressData = queries.in_progress.data;
  const doneData = queries.done.data;
  const shown = useMemo(
    () =>
      [todoData, progressData, doneData].flatMap(
        (data) => data?.work_items.items ?? [],
      ),
    [todoData, progressData, doneData],
  );

  // Everyone who has had a card on screen, plus everyone who could be given
  // one, so a reader who cannot assign still sees whose cards there are, and
  // a person's chip stays while another person's cards are the ones shown.
  const [seen, setSeen] = useState<Map<string, string>>(new Map());
  useEffect(() => {
    setSeen((known) => {
      let next = known;
      for (const { assignee_id: id, assignee_name: name } of shown) {
        if (id && name && !next.has(id)) {
          if (next === known) next = new Map(known);
          next.set(id, name);
        }
      }
      return next;
    });
  }, [shown]);
  const people = useMemo<BoardPerson[]>(() => {
    const byId = new Map<string, string>();
    for (const member of members) byId.set(member.id, member.name);
    for (const [id, name] of seen) byId.set(id, name);
    return [...byId].map(([id, name]) => ({ id, name }));
  }, [members, seen]);

  if (isPhone) return <Navigate to="/warehouse/todo" replace />;

  const cards = (state: ColumnState) =>
    queries[state].data?.work_items.items ?? [];

  const giveTo = (item: WorkItem, assigneeId: string | null) =>
    assign.mutate({
      sourceKind: item.source_kind,
      sourceId: item.source_id,
      assigneeId,
    });

  return (
    <div className="space-y-4">
      <ReadOnlyNotice module="warehouse" />
      {isLoading ? (
        <LoadingSpinner />
      ) : isError ? (
        <QueryError
          message={t("errors.loadDocumentsFailed")}
          onRetry={() => void refetch()}
        />
      ) : (
        <>
          <BoardPeople
            people={people}
            value={person}
            onChange={setPerson}
            dropEnabled={canWrite && dragged !== null}
            onDropOn={(assigneeId) => {
              if (dragged) giveTo(dragged, assigneeId);
              setDragged(null);
            }}
          />
          <BoardMeasures
            measures={measures.data}
            failed={measures.isError}
            overdue={late ? late.work_items.total : null}
            overdueFailed={lateFailed}
          />
          {canWrite && membersFailed && (
            <p role="alert" className="text-sm text-on-warning">
              {t("todo.membersFailed")}
            </p>
          )}
          <div className="grid grid-cols-[repeat(auto-fit,minmax(18rem,1fr))] items-start gap-4">
            {COLUMN_STATES.map((state) => (
              <section
                key={state}
                aria-label={columnTitle(t, state)}
                className="flex flex-col gap-2.5 rounded-xl bg-surface-raised p-3"
              >
                <div className="flex items-center gap-2 px-1 pt-1">
                  <h2 className="text-sm font-semibold text-on">
                    {columnTitle(t, state)}
                  </h2>
                  <span className="rounded-full bg-surface-card px-2 py-0.5 text-xs text-on-secondary">
                    {queries[state].data?.work_items.total ?? 0}
                  </span>
                </div>
                {cards(state).length === 0 &&
                  !(state === "todo" && canWrite) && (
                    <p className="px-1 text-sm text-on-secondary">
                      {t("board.empty")}
                    </p>
                  )}
                {cards(state).map((item) => (
                  <BoardCard
                    key={item.key}
                    item={item}
                    members={members}
                    canWrite={canWrite}
                    canAssign={!membersFailed}
                    dragging={dragged?.key === item.key}
                    onDragStart={setDragged}
                    onDragEnd={() => setDragged(null)}
                    onAssign={giveTo}
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
                  />
                ))}
                <MoreCards
                  shown={cards(state).length}
                  total={queries[state].data?.work_items.total ?? 0}
                  limit={limits[state]}
                  onMore={() =>
                    setLimits((current) => ({
                      ...current,
                      [state]: Math.min(current[state] + PAGE_SIZE, MAX_TASKS),
                    }))
                  }
                />
                {state === "todo" &&
                  canWrite &&
                  (adding ? (
                    <AddTaskForm
                      members={members}
                      onCreated={() => setAdding(false)}
                    />
                  ) : (
                    <Button
                      type="button"
                      variant="outline"
                      className="w-full border-dashed"
                      leftIcon={<Plus size={16} aria-hidden="true" />}
                      onClick={() => setAdding(true)}
                    >
                      {t("board.addOwn")}
                    </Button>
                  ))}
              </section>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
