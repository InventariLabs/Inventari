import { act } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import userEvent from "@testing-library/user-event";
import { render, screen } from "@/test/utils";
import * as todoHooks from "@/modules/warehouse/hooks/useDocumentsTodo";
import type { WorkItem } from "@/modules/warehouse/types";
import DocumentsBoardPage from "./DocumentsBoardPage";

const m = vi.hoisted(() => ({
  navigate: vi.fn(),
  assign: vi.fn(),
  done: vi.fn(),
  remove: vi.fn(),
  startCount: vi.fn(),
  cards: {} as Record<string, Record<string, unknown>>,
  people: {} as Record<string, unknown>,
}));

vi.mock("react-router-dom", async (importOriginal) => ({
  ...(await importOriginal<typeof import("react-router-dom")>()),
  useNavigate: () => m.navigate,
}));
vi.mock("@/hooks/useCanWrite", () => ({
  useCanWrite: () => true,
  useCanManage: () => true,
}));
vi.mock("@/hooks/useMediaQuery", () => ({ useMediaQuery: () => false }));
vi.mock("@/hooks/useModulePageHeader", () => ({
  useModulePageHeader: () => ({ setHeader: vi.fn() }),
}));
vi.mock("@/modules/warehouse/hooks/useDocumentsTodo", () => ({
  useDocumentsTodo: vi.fn(),
  MAX_TASKS: 1000,
}));
vi.mock("@/modules/warehouse/hooks/useWorkItems", () => ({
  useAssignableMembers: () => ({ data: [{ id: "user-anna", name: "Anna" }] }),
  useAssignWorkItem: () => ({ mutate: m.assign }),
  useSetCustomWorkItemDone: () => ({ mutate: m.done }),
  useDeleteCustomWorkItem: () => ({ mutate: m.remove }),
  useStartCount: () => ({ mutate: m.startCount }),
  useCreateCustomWorkItem: () => ({ mutate: vi.fn(), isPending: false }),
  useWorkMeasures: () => ({ data: undefined, isError: false }),
}));

// The card and the people strip have their own tests; here they are stubs
// that record the callbacks the board handed them.
vi.mock("@/modules/warehouse/components/board/BoardCard", () => ({
  BoardCard: (p: { item: WorkItem } & Record<string, unknown>) => {
    m.cards[p.item.key] = p;
    return <div>{p.item.subject}</div>;
  },
}));
vi.mock("@/modules/warehouse/components/board/BoardPeople", () => ({
  BoardPeople: (p: Record<string, unknown>) => {
    Object.assign(m.people, p);
    return null;
  },
}));

function card(over: Partial<WorkItem>): WorkItem {
  return {
    key: "custom:t1",
    kind: "custom",
    state: "todo",
    source_kind: "custom",
    source_id: "t1",
    overdue: false,
    shelf_scan_required: false,
    next_action: null,
    subject: "Sweep aisle 3",
    ...over,
  } as WorkItem;
}

/** Each column serves the cards of its state; `total` may claim more. */
function serve(
  items: WorkItem[],
  totals: Partial<Record<string, number>> = {},
) {
  const refetch = vi.fn(() => Promise.resolve());
  vi.mocked(todoHooks.useDocumentsTodo).mockImplementation(((params?: {
    state?: string;
    limit?: number;
  }) => {
    const narrowed = items.filter(
      (i) => !params?.state || i.state === params.state,
    );
    return {
      data: {
        work_items: {
          items: narrowed,
          total: totals[params?.state ?? ""] ?? narrowed.length,
        },
        decisions: { quarantine: { items: [], total: 0 } },
      },
      isLoading: false,
      isError: false,
      refetch,
    };
  }) as unknown as typeof todoHooks.useDocumentsTodo);
  return refetch;
}

type Fn = (...args: unknown[]) => unknown;
function press(
  props: Record<string, unknown>,
  name: string,
  ...args: unknown[]
) {
  act(() => {
    (props[name] as Fn)(...args);
  });
}

/**
 * What the board does with what a card asks for. These catch a tick that
 * marks the wrong task done, a delete or a count start aimed at another
 * record, a count that starts but never opens the counting screen, a drag
 * that forgets whom it was dropped on, and a "Show more" that asks for no
 * more cards.
 */
describe("DocumentsBoardPage — card actions reach the record behind the card", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    m.cards = {};
    for (const key of Object.keys(m.people)) delete m.people[key];
  });

  it("marks a hand-made task done and deletes it by its own id", () => {
    const task = card({});
    serve([task]);
    render(<DocumentsBoardPage />);
    press(m.cards[task.key], "onToggleDone", task, true);
    expect(m.done).toHaveBeenCalledWith({ id: "t1", done: true });
    press(m.cards[task.key], "onDelete", task);
    expect(m.remove).toHaveBeenCalledWith("t1");
  });

  it("starts the count a card names and opens its counting screen", () => {
    const count = card({
      key: "count:c1",
      kind: "count",
      source_kind: "count",
      source_id: "c1",
    } as Partial<WorkItem>);
    serve([count]);
    render(<DocumentsBoardPage />);
    press(m.cards[count.key], "onStartCount", count);
    expect(m.startCount).toHaveBeenCalledWith("c1", expect.any(Object));
    const opts = m.startCount.mock.calls[0][1] as {
      onSuccess: (st: { id: string }) => void;
    };
    act(() => opts.onSuccess({ id: "st-9" }));
    expect(m.navigate).toHaveBeenCalledWith(
      "/inventory/stock-takes/st-9/counting",
    );
  });

  it("gives the dragged card to the person it is dropped on", () => {
    const task = card({});
    serve([task]);
    render(<DocumentsBoardPage />);
    press(m.cards[task.key], "onDragStart", task);
    expect(m.people.dropEnabled).toBe(true);
    press(m.people, "onDropOn", "user-anna");
    expect(m.assign).toHaveBeenCalledWith({
      sourceKind: "custom",
      sourceId: "t1",
      assigneeId: "user-anna",
    });
    expect(m.people.dropEnabled).toBe(false);
  });

  it("assigns nothing when the drag ended before a drop", () => {
    const task = card({});
    serve([task]);
    render(<DocumentsBoardPage />);
    press(m.cards[task.key], "onDragStart", task);
    press(m.cards[task.key], "onDragEnd");
    expect(m.people.dropEnabled).toBe(false);
    press(m.people, "onDropOn", "user-anna");
    expect(m.assign).not.toHaveBeenCalled();
  });

  it("asks a column for another page of cards", async () => {
    serve([card({})], { todo: 250 });
    const user = userEvent.setup();
    render(<DocumentsBoardPage />);
    const todoLimit = () =>
      vi
        .mocked(todoHooks.useDocumentsTodo)
        .mock.calls.filter(
          (c) => (c[0] as { state?: string })?.state === "todo",
        )
        .map((c) => (c[0] as { limit: number }).limit)
        .pop();
    expect(todoLimit()).toBe(100);
    await user.click(screen.getByRole("button", { name: "Show more" }));
    expect(todoLimit()).toBe(200);
  });

  it("refetches every column from the failure", async () => {
    const refetch = vi.fn(() => Promise.resolve());
    vi.mocked(todoHooks.useDocumentsTodo).mockReturnValue({
      data: undefined,
      isLoading: false,
      isError: true,
      refetch,
    } as unknown as ReturnType<typeof todoHooks.useDocumentsTodo>);
    const user = userEvent.setup();
    render(<DocumentsBoardPage />);
    await user.click(screen.getByRole("button", { name: "Try again" }));
    // The three columns, not only the one that failed first.
    expect(refetch).toHaveBeenCalledTimes(3);
  });
});
