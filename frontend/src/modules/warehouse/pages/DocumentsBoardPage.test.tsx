import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, within } from "@/test/utils";
import userEvent from "@testing-library/user-event";
import DocumentsBoardPage from "./DocumentsBoardPage";
import * as todoHooks from "@/modules/warehouse/hooks/useDocumentsTodo";
import { startOfDayIso } from "@/modules/warehouse/components/board/boardColumns";
import type { WorkItem, WorkItemMeasures } from "@/modules/warehouse/types";

const rights = vi.hoisted(() => ({ write: true }));
const phone = vi.hoisted(() => ({ is: false }));
const late = vi.hoisted(() => ({ fails: false }));
const mutations = vi.hoisted(() => ({
  assign: vi.fn(),
  done: vi.fn(),
  remove: vi.fn(),
  create: vi.fn(),
  startCount: vi.fn(),
}));
const measuresState = vi.hoisted(() => ({
  data: undefined as unknown,
  isError: false,
}));

vi.mock("@/hooks/useCanWrite", () => ({
  useCanWrite: () => rights.write,
  useCanManage: () => rights.write,
}));
vi.mock("@/hooks/useMediaQuery", () => ({
  useMediaQuery: () => phone.is,
}));
vi.mock("@/hooks/useModulePageHeader", () => ({
  useModulePageHeader: () => ({ setHeader: vi.fn() }),
}));
vi.mock("@/modules/warehouse/hooks/useDocumentsTodo", () => ({
  useDocumentsTodo: vi.fn(),
  MAX_TASKS: 1000,
}));
vi.mock("@/modules/warehouse/hooks/useWorkItems", () => ({
  useAssignableMembers: () => ({
    data: [
      { id: "user-anna", name: "Anna Nowak" },
      { id: "user-marek", name: "Marek Lis" },
    ],
  }),
  useAssignWorkItem: () => ({ mutate: mutations.assign }),
  useSetCustomWorkItemDone: () => ({ mutate: mutations.done }),
  useDeleteCustomWorkItem: () => ({ mutate: mutations.remove }),
  useStartCount: () => ({ mutate: mutations.startCount }),
  useCreateCustomWorkItem: () => ({
    mutate: mutations.create,
    isPending: false,
  }),
  useWorkMeasures: () => measuresState,
}));

function card(over: Partial<WorkItem>): WorkItem {
  return {
    key: "document:d",
    kind: "ship",
    state: "todo",
    source_kind: "document",
    source_id: "d",
    overdue: false,
    shelf_scan_required: false,
    next_action: "pick",
    subject: "Bistro Lato",
    number: "WZ/1",
    count: "5",
    document_type: "OUT",
    document_status: "CONFIRMED",
    ...over,
  } as WorkItem;
}

/** A server that narrows by column, person and view before it cuts a page. */
function serve(items: WorkItem[]) {
  vi.mocked(todoHooks.useDocumentsTodo).mockImplementation(((params?: {
    state?: WorkItem["state"];
    assignee?: string;
    view?: string;
    limit?: number;
  }) => {
    const { state, assignee, view, limit = 100 } = params ?? {};
    const narrowed = items.filter(
      (item) =>
        (!state || item.state === state) &&
        (!assignee ||
          (assignee === "none"
            ? !item.assignee_id
            : item.assignee_id === assignee)) &&
        (view !== "overdue" || (item.overdue && item.state !== "done")),
    );
    if (view === "overdue" && late.fails) {
      return {
        data: undefined,
        isLoading: false,
        isError: true,
        refetch: vi.fn(),
      };
    }
    return {
      data: {
        work_items: { items: narrowed.slice(0, limit), total: narrowed.length },
        decisions: { quarantine: { items: [], total: 0 } },
      },
      isLoading: false,
      isError: false,
      refetch: vi.fn(),
    };
  }) as unknown as typeof todoHooks.useDocumentsTodo);
}

function column(name: string) {
  return screen.getByRole("region", { name });
}

const MEASURES: WorkItemMeasures = {
  dock_to_stock_seconds: 9600,
  dock_to_stock_count: 3,
  shipped_same_day: 7,
  shipped_total: 9,
};

describe("DocumentsBoardPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    rights.write = true;
    phone.is = false;
    late.fails = false;
    measuresState.data = MEASURES;
    measuresState.isError = false;
  });

  it("puts each card in the column of its state", () => {
    serve([
      card({ key: "a", source_id: "a", subject: "Alpha", state: "todo" }),
      card({
        key: "b",
        source_id: "b",
        subject: "Bravo",
        state: "in_progress",
        lines_done: 1,
      }),
      card({
        key: "c",
        source_id: "c",
        subject: "Charlie",
        state: "done",
        next_action: null,
        done_at: new Date().toISOString(),
      }),
    ]);

    render(<DocumentsBoardPage />);

    expect(within(column("To do")).getByText(/Alpha/)).toBeInTheDocument();
    expect(
      within(column("In progress")).getByText(/Bravo/),
    ).toBeInTheDocument();
    expect(
      within(column("Done today")).getByText(/Charlie/),
    ).toBeInTheDocument();
  });

  it("shows how far a card under way has got", () => {
    serve([
      card({
        key: "b",
        source_id: "b",
        state: "in_progress",
        count: "3",
        lines_done: 2,
      }),
    ]);

    render(<DocumentsBoardPage />);

    expect(screen.getByRole("progressbar")).toHaveAttribute(
      "aria-valuenow",
      "67",
    );
  });

  it("accepts no card dropped on a column, so a card cannot be moved by hand", () => {
    serve([card({ key: "a", source_id: "a", subject: "Alpha" })]);

    render(<DocumentsBoardPage />);

    const done = column("Done today");
    const dropped = fireEvent.drop(done, {
      dataTransfer: { getData: () => "a" },
    });
    // A drop is only allowed where dragover was cancelled; nothing cancels it.
    const over = fireEvent.dragOver(done);
    expect(over).toBe(true);
    expect(dropped).toBe(true);
    expect(mutations.assign).not.toHaveBeenCalled();
    expect(mutations.done).not.toHaveBeenCalled();
    expect(within(column("To do")).getByText(/Alpha/)).toBeInTheDocument();
  });

  it("narrows to one person and to the cards nobody has", async () => {
    const user = userEvent.setup();
    serve([
      card({
        key: "a",
        source_id: "a",
        subject: "Alpha",
        assignee_id: "user-anna",
        assignee_name: "Anna Nowak",
      }),
      card({
        key: "b",
        source_id: "b",
        subject: "Bravo",
        assignee_id: "user-marek",
        assignee_name: "Marek Lis",
      }),
      card({ key: "c", source_id: "c", subject: "Charlie" }),
    ]);

    render(<DocumentsBoardPage />);
    const chips = screen.getByRole("group", { name: "Whose work" });

    await user.click(within(chips).getByRole("button", { name: "Anna Nowak" }));
    expect(screen.getByText(/Alpha/)).toBeInTheDocument();
    expect(screen.queryByText(/Bravo/)).not.toBeInTheDocument();

    await user.click(within(chips).getByRole("button", { name: "Unassigned" }));
    expect(screen.getByText(/Charlie/)).toBeInTheDocument();
    expect(screen.queryByText(/Alpha/)).not.toBeInTheDocument();

    await user.click(within(chips).getByRole("button", { name: "Everyone" }));
    expect(screen.getByText(/Bravo/)).toBeInTheDocument();
  });

  it("says a stage holder is the one working on the card, apart from who it is assigned to", () => {
    serve([
      card({
        key: "document:a",
        source_id: "a",
        subject: "Alpha",
        state: "in_progress",
        place: "Dock",
        stage_holder_name: "Piotr Picker",
      }),
    ]);

    render(<DocumentsBoardPage />);

    const article = screen.getByText(/Alpha/).closest("article") as HTMLElement;
    expect(
      within(article).getByText("In progress · Piotr Picker"),
    ).toBeInTheDocument();
  });

  it("gives a card to the person it is dropped on, or takes it back", () => {
    serve([
      card({
        key: "document:a",
        source_id: "a",
        subject: "Alpha",
        assignee_id: "user-marek",
        assignee_name: "Marek Lis",
      }),
    ]);

    render(<DocumentsBoardPage />);
    const chips = screen.getByRole("group", { name: "Whose work" });
    const article = screen.getByText(/Alpha/).closest("article") as HTMLElement;

    fireEvent.dragStart(article, { dataTransfer: { setData: vi.fn() } });
    fireEvent.drop(within(chips).getByRole("button", { name: "Anna Nowak" }));

    expect(mutations.assign).toHaveBeenCalledWith({
      sourceKind: "document",
      sourceId: "a",
      assigneeId: "user-anna",
    });

    fireEvent.dragStart(article, { dataTransfer: { setData: vi.fn() } });
    fireEvent.drop(within(chips).getByRole("button", { name: "Unassigned" }));

    expect(mutations.assign).toHaveBeenLastCalledWith({
      sourceKind: "document",
      sourceId: "a",
      assigneeId: null,
    });
  });

  it("gives a card to a person from the keyboard", async () => {
    const user = userEvent.setup();
    serve([card({ key: "document:a", source_id: "a", subject: "Alpha" })]);

    render(<DocumentsBoardPage />);
    await user.selectOptions(
      screen.getByRole("combobox", { name: /Give to someone/ }),
      "user-marek",
    );

    expect(mutations.assign).toHaveBeenCalledWith({
      sourceKind: "document",
      sourceId: "a",
      assigneeId: "user-marek",
    });
  });

  it("adds a card of your own with a person and a day", async () => {
    const user = userEvent.setup();
    serve([]);

    render(<DocumentsBoardPage />);
    await user.click(screen.getByRole("button", { name: /Add your own card/ }));
    await user.type(screen.getByLabelText("New task"), "Move the rack");
    await user.selectOptions(screen.getByLabelText("Person"), "user-anna");
    await user.click(screen.getByRole("button", { name: "Add" }));

    expect(mutations.create).toHaveBeenCalledWith(
      { title: "Move the rack", due_date: null, assignee_id: "user-anna" },
      expect.anything(),
    );
  });

  it("ticks a card of your own off", async () => {
    const user = userEvent.setup();
    serve([
      card({
        key: "custom:x",
        kind: "custom",
        source_kind: "custom",
        source_id: "x",
        subject: "Move the rack",
        next_action: null,
        number: null,
        count: null,
      }),
    ]);

    render(<DocumentsBoardPage />);
    await user.click(screen.getByRole("checkbox", { name: /Mark as done/ }));

    expect(mutations.done).toHaveBeenCalledWith({ id: "x", done: true });
  });

  it("asks for Done from the start of the reader's own day", () => {
    serve([]);

    render(<DocumentsBoardPage />);

    const asks = vi
      .mocked(todoHooks.useDocumentsTodo)
      .mock.calls.map(([params]) => params);
    const done = asks.find((params) => params?.state === "done");
    expect(done?.doneSince).toBe(startOfDayIso(new Date()));
    expect(
      asks
        .filter((params) => params?.state !== "done")
        .map((p) => p?.doneSince),
    ).toEqual([undefined, undefined, undefined]);
  });

  it("asks the server for a person's cards instead of filtering a page", async () => {
    const user = userEvent.setup();
    serve([]);

    render(<DocumentsBoardPage />);
    const chips = screen.getByRole("group", { name: "Whose work" });
    await user.click(within(chips).getByRole("button", { name: "Anna Nowak" }));
    await user.click(within(chips).getByRole("button", { name: "Unassigned" }));

    const asked = vi
      .mocked(todoHooks.useDocumentsTodo)
      .mock.calls.map(([params]) => params?.assignee);
    expect(asked).toContain("user-anna");
    expect(asked).toContain("none");
  });

  it("counts a column and the late cards over all of them, and shows more on request", async () => {
    const user = userEvent.setup();
    serve(
      Array.from({ length: 130 }, (_, index) =>
        card({
          key: `d${index}`,
          source_id: `d${index}`,
          subject: `Card ${index}`,
          overdue: true,
        }),
      ),
    );

    render(<DocumentsBoardPage />);

    const todo = column("To do");
    expect(within(todo).getAllByRole("article")).toHaveLength(100);
    expect(within(todo).getByText("130")).toBeInTheDocument();
    expect(screen.getByText("130 cards")).toBeInTheDocument();
    expect(
      within(todo).getByText("Showing 100 of 130 cards."),
    ).toBeInTheDocument();

    await user.click(within(todo).getByRole("button", { name: "Show more" }));

    expect(vi.mocked(todoHooks.useDocumentsTodo)).toHaveBeenCalledWith(
      expect.objectContaining({ state: "todo", limit: 200 }),
    );
    expect(within(column("To do")).getAllByRole("article")).toHaveLength(130);
  });

  it("shows the week's measures and counts the late cards", () => {
    serve([
      card({ key: "a", source_id: "a", overdue: true }),
      card({ key: "b", source_id: "b", overdue: true, state: "in_progress" }),
      card({ key: "c", source_id: "c", overdue: true, state: "done" }),
    ]);

    render(<DocumentsBoardPage />);

    expect(screen.getByText("on average 2 h 40 min")).toBeInTheDocument();
    expect(screen.getByText("7 of 9 this week")).toBeInTheDocument();
    expect(screen.getByText("2 cards")).toBeInTheDocument();
  });

  it("does not call the late cards none when they could not be counted", () => {
    late.fails = true;
    serve([card({ key: "a", source_id: "a", overdue: true })]);

    render(<DocumentsBoardPage />);

    expect(screen.queryByText("None")).not.toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent(
      "The week's numbers could not be loaded.",
    );
  });

  it("says so when the week's numbers could not be read", () => {
    measuresState.data = undefined;
    measuresState.isError = true;
    serve([]);

    render(<DocumentsBoardPage />);

    expect(screen.getByRole("alert")).toHaveTextContent(
      "The week's numbers could not be loaded.",
    );
  });

  it("offers a reader without write rights no assigning and no adding", () => {
    rights.write = false;
    serve([card({ key: "a", source_id: "a", subject: "Alpha" })]);

    render(<DocumentsBoardPage />);

    expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /Add your own card/ }),
    ).not.toBeInTheDocument();
    expect(screen.getByText(/Alpha/).closest("article")).toHaveAttribute(
      "draggable",
      "false",
    );
  });

  it("sends a phone to its own list of work", () => {
    phone.is = true;
    serve([]);

    render(<DocumentsBoardPage />);

    expect(screen.queryByRole("group", { name: "Whose work" })).toBeNull();
  });
});
