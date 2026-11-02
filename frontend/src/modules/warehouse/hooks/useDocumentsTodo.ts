import { keepPreviousData } from "@tanstack/react-query";
import { documentsApi } from "@/modules/warehouse/api/documents";
import { queryKeys } from "@/hooks/queries/keys";
import { useModuleQuery } from "@/hooks/queries/useModuleQuery";
import { todayIso } from "@/utils/formatters";

/** The server's cap on the document lists that come with the tasks. */
const DOCUMENT_LIST_LIMIT = 200;

/** The most tasks the server lists in one answer. */
export const MAX_TASKS = 1000;

/**
 * What the floor has to do, as one list of tasks: documents to receive or
 * ship, orders expected, production planned, approvals waiting, counts due
 * and the tasks somebody added by hand. The server derives each task's state
 * and next action from the record behind it and counts every task, not the
 * rows of one page. The decisions beside it (quarantine holds) come in the
 * same answer. `limit` is how many tasks to list, up to `MAX_TASKS`; `view`
 * narrows them on the server, so a filter finds its tasks wherever they lie.
 */
export function useDocumentsTodo({
  limit = 100,
  view = "all",
  state,
  assignee,
  locationId,
  includeDone = false,
  doneSince,
  refetchInterval,
}: {
  limit?: number;
  view?: "all" | "mine" | "overdue";
  /** Only the tasks in one board column, counted and cut on the server. */
  state?: "todo" | "in_progress" | "done";
  /** Only one person's tasks (a user id), or `none` for nobody's. */
  assignee?: string;
  /** Only the documents and put-away tasks of one warehouse. */
  locationId?: string | null;
  /** Also list the work finished in the last day (the board's third column). */
  includeDone?: boolean;
  /** …or since this instant, for a reader's own calendar day. */
  doneSince?: string;
  /** Re-read the list on this interval, so a screen left open follows events. */
  refetchInterval?: number;
} = {}) {
  return useModuleQuery("warehouse", {
    queryKey: [
      ...queryKeys.documents.all,
      "todo",
      limit,
      view,
      state,
      assignee,
      locationId,
      includeDone,
      doneSince,
    ],
    queryFn: () =>
      documentsApi.todo({
        date_to: todayIso(),
        limit: Math.min(limit, DOCUMENT_LIST_LIMIT),
        work_limit: limit,
        view,
        state,
        assignee,
        location_id: locationId ?? undefined,
        include_done: includeDone || undefined,
        done_since: doneSince,
      }),
    refetchInterval,
    // Switching filter or asking for more keeps the list on screen meanwhile.
    placeholderData: keepPreviousData,
  });
}

/**
 * How many things wait in To do — the launcher's badge count.
 *
 * Quarantine holds count too: a batch in quarantine is work somebody has to
 * answer for today, and a badge that ignored it would say "nothing to do"
 * over a page that asks for a decision.
 */
export function fetchDocumentsTodoCount(): Promise<number> {
  return documentsApi
    .todo({ date_to: todayIso(), limit: 1 })
    .then((queue) => queue.work_items.total + queue.decisions.quarantine.total);
}
