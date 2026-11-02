import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor, within } from "@/test/utils";
import { http, HttpResponse } from "msw";
import { server } from "@/test/mocks/server";
import { serveLocations } from "@/test/serveLocations";
import userEvent from "@testing-library/user-event";
import { toast } from "sonner";
import DocumentsTodoPage from "./DocumentsTodoPage";
import * as modulesCtx from "@/contexts/ModulesContext";
import * as todoHooks from "@/modules/warehouse/hooks/useDocumentsTodo";
import { useTodayActivity } from "@/modules/warehouse/hooks/useTodayActivity";
import { useAuthStore } from "@/store/authStore";
import type {
  DocumentsTodoResponse,
  TodoDecisions,
  WarehouseDocument,
  WarehouseDocumentRow,
  WorkItem,
} from "@/modules/warehouse/types";
import { documentRow } from "@/test/factories/documents";

const navigateMock = vi.hoisted(() => vi.fn());
const rights = vi.hoisted(() => ({ write: true, orders: true }));
const mutations = vi.hoisted(() => ({
  assign: vi.fn(),
  done: vi.fn(),
  remove: vi.fn(),
  create: vi.fn(),
  startCount: vi.fn(),
  putAway: vi.fn(),
}));

vi.mock("@/hooks/useCanWrite", () => ({
  useCanWrite: (module: string) =>
    module === "purchase_orders" ? rights.orders : rights.write,
  useCanManage: () => rights.write,
}));

vi.mock("sonner", async (importOriginal) => ({
  ...(await importOriginal<typeof import("sonner")>()),
  toast: { success: vi.fn(), error: vi.fn() },
}));

const headerStub = vi.hoisted(() => ({ setHeader: vi.fn() }));

vi.mock("@/hooks/useModulePageHeader", () => ({
  useModulePageHeader: () => ({ setHeader: headerStub.setHeader }),
}));

const storageTree = vi.hoisted(() => ({
  data: [] as Array<{ id: string; name: string }>,
  failed: false,
  asked: [] as unknown[][],
}));

vi.mock("@/hooks/queries/useStoragesTree", () => ({
  useStoragesTree: (...args: unknown[]) => (
    storageTree.asked.push(args),
    {
      data: storageTree.data,
      isError: storageTree.failed,
    }
  ),
}));

vi.mock("@/modules/warehouse/hooks/useTodayActivity", () => ({
  useTodayActivity: vi.fn(),
}));

// The Start tab and the header link carry the count of approvals waiting.
vi.mock("@/modules/warehouse/hooks/useAwaitingApprovalDocuments", () => ({
  useAwaitingApprovalDocuments: () => ({
    data: { total: 2 },
    isLoading: false,
    isError: false,
  }),
}));

vi.mock("react-router-dom", async () => {
  const actual =
    await vi.importActual<typeof import("react-router-dom")>(
      "react-router-dom",
    );
  return { ...actual, useNavigate: () => navigateMock };
});

vi.mock("@/modules/warehouse/components/picking/WmsPickingView", () => ({
  default: ({ documentIds }: { documentIds: string[] }) => (
    <div data-testid="picking-session">{documentIds.join(",")}</div>
  ),
}));

const formStub = vi.hoisted(() => ({
  props: null as {
    initialType?: string;
    initialSourceLocationId?: string;
    initialLines?: Array<Record<string, unknown>>;
  } | null,
}));

vi.mock("@/modules/warehouse/components/DocumentFormModal", () => ({
  default: (props: {
    initialType?: string;
    initialSourceLocationId?: string;
    initialLines?: Array<Record<string, unknown>>;
  }) => {
    formStub.props = props;
    return <div data-testid="document-form-modal">{props.initialType}</div>;
  },
}));

vi.mock("@/modules/warehouse/hooks/useDocumentsTodo", () => ({
  useDocumentsTodo: vi.fn(),
  MAX_TASKS: 1000,
}));

vi.mock("@/modules/warehouse/hooks/useWorkItems", () => ({
  useAssignableMembers: () => ({
    data: [
      { id: "user-me", name: "Me Myself" },
      { id: "user-ann", name: "Ann" },
    ],
  }),
  useAssignWorkItem: () => ({ mutate: mutations.assign }),
  useSetCustomWorkItemDone: () => ({ mutate: mutations.done }),
  useDeleteCustomWorkItem: () => ({ mutate: mutations.remove }),
  useStartCount: () => ({ mutate: mutations.startCount }),
  usePutAwayWorkItem: () => ({ mutate: mutations.putAway, isPending: false }),
  // The Board's deep link opens nothing in these tests; a task is opened by
  // its own row here.
  useOpenReplenishmentLink: () => undefined,
  useCreateCustomWorkItem: () => ({
    mutate: mutations.create,
    isPending: false,
  }),
}));

function decisions(overrides: Partial<TodoDecisions> = {}): TodoDecisions {
  return {
    backorders: { items: [], total: 0 },
    approvals: { items: [], total: 0 },
    quarantine: { items: [], total: 0 },
    ...overrides,
  };
}

function task(overrides: Partial<WorkItem> = {}): WorkItem {
  return {
    key: "document:doc-1",
    kind: "ship",
    state: "todo",
    source_kind: "document",
    source_id: "doc-1",
    overdue: false,
    shelf_scan_required: false,
    next_action: "pick",
    subject: "Bistro Lato",
    number: "WZ/1",
    count: "5",
    document_type: "OUT",
    document_status: "CONFIRMED",
    ...overrides,
  };
}

function queue(
  tasks: WorkItem[],
  waiting: Partial<TodoDecisions> = {},
  total?: number,
): DocumentsTodoResponse {
  return {
    inbound: { items: [], total: 0 },
    outbound: { items: [], total: 0 },
    decisions: decisions(waiting),
    work_items: { items: tasks, total: total ?? tasks.length },
  };
}

function answer(data: DocumentsTodoResponse) {
  vi.mocked(todoHooks.useDocumentsTodo).mockReturnValue({
    data,
    isLoading: false,
    isError: false,
    refetch: vi.fn(),
  } as unknown as ReturnType<typeof todoHooks.useDocumentsTodo>);
}

function enable(...modules: string[]) {
  vi.spyOn(modulesCtx, "useModules").mockReturnValue({
    enabledModules: modules,
    isModuleEnabled: (name: string) => modules.includes(name),
    isLoading: false,
    refreshModules: vi.fn(),
    focusModule: null,
    hiddenModules: [],
  });
}

function feedAnswer(items: WarehouseDocumentRow[] = []) {
  vi.mocked(useTodayActivity).mockReturnValue({
    data: { items, total: items.length },
    isLoading: false,
    isError: false,
    refetch: vi.fn(),
  } as unknown as ReturnType<typeof useTodayActivity>);
}

function postedDocument(overrides: Partial<WarehouseDocument> = {}) {
  return documentRow({
    id: "doc-feed",
    number: "PZ/2026/014",
    type: "IN",
    status: "COMPLETED",
    partner_snapshot: { name: "Mleczarnia Sady" },
    completed_by_name: "Anna",
    completed_at: "2026-10-20T10:42:00Z",
    created_by_name: "Anna",
    source_location_name: null,
    target_location_name: "Main Warehouse",
    lines: Array.from({ length: 6 }, () => ({ name: null })),
    ...overrides,
  } as unknown as WarehouseDocument);
}

/** What the page asks of the viewport; a desktop unless a test says otherwise. */
function viewport({ phone }: { phone: boolean }) {
  window.matchMedia = vi.fn().mockImplementation((query: string) => ({
    matches: phone,
    media: query,
    onchange: null,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  }));
}

describe("DocumentsTodoPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    rights.write = true;
    rights.orders = true;
    formStub.props = null;
    storageTree.data = [];
    storageTree.failed = false;
    feedAnswer();
    viewport({ phone: false });
    useAuthStore.setState({ user: { id: "user-me" } as never });
    enable("warehouse", "stock_takes");
  });

  it("opens on a phone with the whole floor's work and its filters", () => {
    viewport({ phone: true });
    useAuthStore.setState({
      user: { id: "user-me", full_name: "Anna Kowalska" } as never,
    });
    answer(queue([task()]));
    render(<DocumentsTodoPage />);

    expect(todoHooks.useDocumentsTodo).toHaveBeenLastCalledWith({
      limit: 100,
      view: "all",
    });
    expect(headerStub.setHeader.mock.calls.at(-1)?.[0]?.title).toBe(
      "Hello, Anna",
    );
    expect(screen.getByText("Work today")).toBeInTheDocument();
    expect(screen.getByText("in order")).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "All" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    expect(screen.getByRole("tab", { name: "Mine" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Overdue" })).toBeInTheDocument();
  });

  it("narrows a phone's list to the reader's own work under its own title", async () => {
    viewport({ phone: true });
    vi.mocked(todoHooks.useDocumentsTodo).mockImplementation(
      ({ view } = {}) =>
        ({
          data: queue(
            view === "mine" ? [task({ assignee_id: "user-me" })] : [task()],
          ),
          isLoading: false,
          isError: false,
          refetch: vi.fn(),
        }) as unknown as ReturnType<typeof todoHooks.useDocumentsTodo>,
    );
    render(<DocumentsTodoPage />);

    await userEvent.click(screen.getByRole("tab", { name: "Mine" }));

    expect(todoHooks.useDocumentsTodo).toHaveBeenLastCalledWith({
      limit: 100,
      view: "mine",
    });
    expect(screen.getByText("My work today")).toBeInTheDocument();
    expect(screen.queryByText("Work today")).not.toBeInTheDocument();
  });

  it("takes an unassigned task for the reader before opening it on a phone", async () => {
    viewport({ phone: true });
    answer(queue([task({ assignee_id: null })]));
    mutations.assign.mockImplementation(
      (_vars: unknown, options?: { onSuccess?: () => void }) =>
        options?.onSuccess?.(),
    );
    render(<DocumentsTodoPage />);

    await userEvent.click(screen.getByRole("button", { name: "Pick" }));

    expect(mutations.assign).toHaveBeenCalledWith(
      {
        sourceKind: "document",
        sourceId: "doc-1",
        assigneeId: "user-me",
        onlyIfUnassigned: true,
      },
      expect.anything(),
    );
    expect(navigateMock).toHaveBeenLastCalledWith(
      "/warehouse/documents/doc-1#pick",
    );
    expect(mutations.assign.mock.invocationCallOrder[0]).toBeLessThan(
      navigateMock.mock.invocationCallOrder[0],
    );
  });

  it("does not open a task somebody else claimed before the tap", async () => {
    viewport({ phone: true });
    answer(queue([task({ assignee_id: null })]));
    // The server refuses the claim (409) — the list was read before somebody
    // else took the task — and the mutation never reports success. Its flow
    // must not open as if it were the reader's.
    mutations.assign.mockImplementation(() => undefined);
    render(<DocumentsTodoPage />);

    await userEvent.click(screen.getByRole("button", { name: "Pick" }));

    expect(mutations.assign).toHaveBeenCalledWith(
      expect.objectContaining({ onlyIfUnassigned: true }),
      expect.anything(),
    );
    expect(navigateMock).not.toHaveBeenCalled();
  });

  it("opens a task already given to somebody without taking it", async () => {
    viewport({ phone: true });
    answer(queue([task({ assignee_id: "user-ann", assignee_name: "Ann" })]));
    render(<DocumentsTodoPage />);

    await userEvent.click(screen.getByRole("button", { name: "Pick" }));

    expect(mutations.assign).not.toHaveBeenCalled();
    expect(navigateMock).toHaveBeenLastCalledWith(
      "/warehouse/documents/doc-1#pick",
    );
  });

  it("leaves choosing a person off a phone's row and names the holder", () => {
    viewport({ phone: true });
    answer(queue([task({ assignee_id: "user-ann", assignee_name: "Ann" })]));
    render(<DocumentsTodoPage />);

    expect(
      screen.queryByRole("combobox", { name: /Give to someone/ }),
    ).not.toBeInTheDocument();
    expect(screen.getByText("Ann")).toBeInTheDocument();
  });

  it("leaves the task with nobody when a desktop opens it", async () => {
    answer(queue([task({ assignee_id: null })]));
    render(<DocumentsTodoPage />);

    await userEvent.click(screen.getByRole("button", { name: "Pick" }));

    expect(mutations.assign).not.toHaveBeenCalled();
    expect(navigateMock).toHaveBeenLastCalledWith(
      "/warehouse/documents/doc-1#pick",
    );
  });

  it("marks overdue work on a phone", () => {
    viewport({ phone: true });
    answer(
      queue([
        task({
          overdue: true,
          due_date: "2026-01-01",
          subject: "Late Ltd",
        }),
      ]),
    );
    render(<DocumentsTodoPage />);

    expect(screen.getByText(/Late Ltd/)).toBeInTheDocument();
    expect(screen.getByText(/^Overdue since /)).toBeInTheDocument();
  });

  it("keeps the whole floor's queue and its filters on a desktop", () => {
    answer(queue([task()]));
    render(<DocumentsTodoPage />);

    expect(todoHooks.useDocumentsTodo).toHaveBeenLastCalledWith({
      limit: 100,
      view: "all",
    });
    expect(headerStub.setHeader.mock.calls.at(-1)?.[0]?.title).toBe(
      "What are we doing?",
    );
    expect(screen.getByRole("tab", { name: "All" })).toBeInTheDocument();
    expect(screen.queryByText("My work today")).not.toBeInTheDocument();
  });

  it("links to Inventory's stock and stock takes", () => {
    answer(queue([task()]));
    render(<DocumentsTodoPage />);
    expect(screen.getByRole("link", { name: "Stock" })).toHaveAttribute(
      "href",
      "/inventory/stock",
    );
    expect(screen.getByRole("link", { name: "Stock takes" })).toHaveAttribute(
      "href",
      "/inventory/stock-takes",
    );
  });

  it("opens the scan screen from the start screen on a desktop", () => {
    answer(queue([task()]));
    render(<DocumentsTodoPage />);
    expect(screen.getByRole("link", { name: "Scan a code" })).toHaveAttribute(
      "href",
      "/warehouse/scan",
    );
  });

  it("offers no approvals queue to an account that may not approve", () => {
    // The link opened a page saying "Approving is not something your account
    // can do": a control that refuses after the click.
    useAuthStore.setState({
      user: { id: "user-me", permissions: ["documents:read"] } as never,
    });
    enable("warehouse", "approvals");
    answer(queue([task()]));
    render(<DocumentsTodoPage />);

    const actions = headerStub.setHeader.mock.calls.at(-1)?.[0]?.actions;
    render(<>{actions}</>);
    expect(
      screen.queryByRole("link", { name: /To approve/ }),
    ).not.toBeInTheDocument();
  });

  it("keeps the approvals queue a link away, with the count as its badge", () => {
    useAuthStore.setState({
      user: { id: "user-me", permissions: ["approvals:approve"] } as never,
    });
    enable("warehouse", "approvals");
    answer(queue([task()]));
    render(<DocumentsTodoPage />);

    const actions = headerStub.setHeader.mock.calls.at(-1)?.[0]?.actions;
    render(<>{actions}</>);
    expect(screen.getByRole("link", { name: /To approve/ })).toHaveAttribute(
      "href",
      "/warehouse/approvals",
    );
  });

  it("offers no stock takes link where the module is off", () => {
    enable("warehouse");
    answer(queue([task()]));
    render(<DocumentsTodoPage />);
    expect(
      screen.queryByRole("link", { name: "Stock takes" }),
    ).not.toBeInTheDocument();
  });

  it("starts the day with the four actions", async () => {
    answer(queue([task()]));
    render(<DocumentsTodoPage />);

    await userEvent.click(
      screen.getByRole("button", { name: /Receive goods/ }),
    );
    expect(navigateMock).toHaveBeenLastCalledWith("/warehouse/receive");

    // Issue and move are one screen each, not a document form.
    await userEvent.click(screen.getByRole("button", { name: /Issue goods/ }));
    expect(navigateMock).toHaveBeenLastCalledWith("/warehouse/issue", {
      state: { backTo: "/warehouse/todo" },
    });

    await userEvent.click(screen.getByRole("button", { name: /^Move/ }));
    expect(navigateMock).toHaveBeenLastCalledWith("/warehouse/move", {
      state: { backTo: "/warehouse/todo" },
    });

    await userEvent.click(screen.getByRole("button", { name: /^Count/ }));
    expect(navigateMock).toHaveBeenLastCalledWith(
      "/inventory/stock-takes/count",
      { state: { backTo: "/warehouse/todo" } },
    );
  });

  it("tells the day in plain words, naming who posted it and linking the document", () => {
    answer(queue([task()]));
    feedAnswer([postedDocument()]);
    render(<DocumentsTodoPage />);

    expect(
      screen.getByText("Anna: Received 6 products from Mleczarnia Sady"),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "PZ/2026/014" })).toHaveAttribute(
      "href",
      "/warehouse/documents/doc-feed",
    );
  });

  it("reads the warehouses as the top of the tree, not the whole of it", () => {
    storageTree.asked = [];
    answer(queue([task()]));
    render(<DocumentsTodoPage />);

    expect(storageTree.asked.length).toBeGreaterThan(0);
    for (const [usage, options] of storageTree.asked) {
      expect(usage).toBeUndefined();
      expect(options).toMatchObject({ depth: 1, counts: false });
    }
  });

  it("narrows the day to the chosen warehouse", () => {
    answer(queue([task()]));
    storageTree.data = [
      { id: "w-main", name: "Main Warehouse" },
      { id: "w-north", name: "North Warehouse" },
    ];
    render(<DocumentsTodoPage />);

    const lastHeader = headerStub.setHeader.mock.calls.at(-1)?.[0];
    expect(lastHeader?.actions).toBeTruthy();
  });

  it("asks for the chosen warehouse's tasks and says which ones follow it", async () => {
    answer(queue([task()]));
    storageTree.data = [
      { id: "w-main", name: "Main Warehouse" },
      { id: "w-north", name: "North Warehouse" },
    ];
    render(<DocumentsTodoPage />);
    expect(
      screen.queryByText(/Only receipts, dispatches and put-away follow/),
    ).not.toBeInTheDocument();

    const actions = headerStub.setHeader.mock.calls.at(-1)?.[0]?.actions;
    render(<>{actions}</>);
    await userEvent.selectOptions(
      screen.getByRole("combobox", { name: "Location" }),
      "w-north",
    );

    expect(todoHooks.useDocumentsTodo).toHaveBeenLastCalledWith(
      expect.objectContaining({ locationId: "w-north" }),
    );
    expect(
      screen.getByText(/Only receipts, dispatches and put-away follow/),
    ).toBeInTheDocument();
  });

  it("offers no warehouse selector where there is nothing to choose", () => {
    answer(queue([task()]));
    storageTree.data = [{ id: "w-main", name: "Main Warehouse" }];
    render(<DocumentsTodoPage />);

    const lastHeader = headerStub.setHeader.mock.calls.at(-1)?.[0];
    expect(lastHeader?.actions).toBeUndefined();
  });

  it("says so when the storages could not be read", () => {
    answer(queue([task()]));
    storageTree.failed = true;
    render(<DocumentsTodoPage />);

    const actions = headerStub.setHeader.mock.calls.at(-1)?.[0]?.actions;
    render(<>{actions}</>);
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Locations could not be loaded.",
    );
  });

  it("reads each kind of task as a sentence with the one button that does it", async () => {
    answer(
      queue([
        task({
          key: "purchase_order:po-1",
          kind: "expected_delivery",
          source_kind: "purchase_order",
          source_id: "po-1",
          next_action: "receive_delivery",
          subject: "Hurtownia Kowalski",
          number: "ZK/1",
          count: "8",
          document_type: null,
          document_status: null,
        }),
        task({
          key: "document:out-1",
          source_id: "out-1",
          subject: "Bistro Lato",
          count: "5",
        }),
        task({
          key: "production_order:run-1",
          kind: "produce",
          source_kind: "production_order",
          source_id: "run-1",
          next_action: "produce",
          subject: "Cheese",
          count: "4",
          document_type: null,
          document_status: null,
        }),
        task({
          key: "cycle_count:count-1",
          kind: "count",
          source_kind: "cycle_count",
          source_id: "count-1",
          next_action: "count",
          subject: "Fast movers",
          count: "0",
          number: null,
          document_type: null,
          document_status: null,
        }),
        task({
          key: "document:appr-1",
          kind: "approve",
          source_id: "appr-1",
          next_action: "review_approval",
          subject: "Acme",
          number: "PZ/9",
          count: "2",
          document_type: "IN",
          document_status: "PENDING_APPROVAL",
        }),
      ]),
    );
    render(<DocumentsTodoPage />);

    expect(
      screen.getByText("Receive delivery from Hurtownia Kowalski — 8 lines"),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Deliver order for Bistro Lato — 5 lines"),
    ).toBeInTheDocument();
    expect(screen.getByText("Make Cheese × 4")).toBeInTheDocument();
    expect(screen.getByText("Count: Fast movers")).toBeInTheDocument();
    expect(
      screen.getByText("Approve PZ/9 from Acme — 2 lines"),
    ).toBeInTheDocument();

    const go = async (name: string, target: string) => {
      await userEvent.click(screen.getByRole("button", { name }));
      expect(navigateMock).toHaveBeenLastCalledWith(target);
    };
    await go("Receive delivery", "/warehouse/receive?order=po-1");
    await go("Pick", "/warehouse/documents/out-1#pick");
    await go("Make it", "/maker/production/run-1");
    mutations.startCount.mockImplementation(
      (_id: string, options: { onSuccess: (take: { id: string }) => void }) =>
        options.onSuccess({ id: "take-9" }),
    );
    await userEvent.click(screen.getByRole("button", { name: "Count" }));
    expect(mutations.startCount).toHaveBeenCalledWith(
      "count-1",
      expect.anything(),
    );
    expect(navigateMock).toHaveBeenLastCalledWith(
      "/inventory/stock-takes/take-9/counting",
    );
    await go("Review approval", "/warehouse/documents/appr-1");
  });

  it("tells a backorder whose stock has arrived from one still waiting", () => {
    const backorder = (id: string, cover: WorkItem["stock_cover"]) =>
      task({
        key: `document:${id}`,
        kind: "backorder",
        source_id: id,
        next_action: "open_draft",
        subject: null,
        number: `DRAFT-${id}`,
        origin_number: `WZ/${id}`,
        stock_cover: cover,
        document_status: "DRAFT",
      });
    answer(
      queue([
        backorder("1", "full"),
        backorder("2", "partial"),
        backorder("3", "none"),
      ]),
    );
    render(<DocumentsTodoPage />);

    expect(screen.getByText("Can be issued in full")).toBeInTheDocument();
    expect(screen.getByText("Can be issued in part")).toBeInTheDocument();
    expect(screen.getByText("Nothing to issue yet")).toBeInTheDocument();
  });

  it("puts away goods waiting in a receiving area to the suggested shelf, or another", async () => {
    serveLocations([
      { id: "wh-1", name: "Main Warehouse" },
      { id: "shelf-a", name: "Shelf A - Top", parent_id: "wh-1" },
      { id: "shelf-b", name: "Shelf B", parent_id: "wh-1" },
    ]);
    answer(
      queue([
        task({
          key: "putaway:line-1",
          kind: "putaway",
          source_kind: "putaway",
          source_id: "line-1",
          next_action: "put_away",
          subject: "Jasmine Rice",
          count: "40",
          unit: "kg",
          place: "Shelf A - Top",
          place_id: "shelf-a",
          number: null,
          document_type: null,
          document_status: null,
        }),
      ]),
    );
    render(<DocumentsTodoPage />);

    expect(
      screen.getByText("Put away 40 kg Jasmine Rice to Shelf A - Top"),
    ).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Put away" }));

    const dialog = screen.getByRole("dialog", { name: "Put away" });
    const shelf = within(dialog).getByRole("combobox", { name: "Location" });
    await waitFor(() => expect(shelf).toHaveTextContent("Shelf A - Top"));
    await userEvent.click(shelf);
    await userEvent.click(
      await screen.findByRole("button", { name: /Shelf B/ }),
    );
    await userEvent.click(
      within(dialog).getByRole("button", { name: "Put away" }),
    );

    expect(mutations.putAway).toHaveBeenCalledWith(
      { lineId: "line-1", locationId: "shelf-b" },
      expect.anything(),
    );
    expect(navigateMock).not.toHaveBeenCalled();
  });

  it("asks for a shelf when no rule suggests one, and offers putaway only to who may post", async () => {
    answer(
      queue([
        task({
          key: "putaway:line-2",
          kind: "putaway",
          source_kind: "putaway",
          source_id: "line-2",
          next_action: "put_away",
          subject: "Black Beans",
          count: "12",
          place: null,
          place_id: null,
        }),
      ]),
    );
    const { unmount } = render(<DocumentsTodoPage />);

    expect(screen.getByText("Put away 12 Black Beans")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Put away" }));
    const dialog = screen.getByRole("dialog", { name: "Put away" });
    expect(within(dialog).getByLabelText("Location")).toHaveValue("");
    expect(
      within(dialog).getByRole("button", { name: "Put away" }),
    ).toBeDisabled();
    // The locations could be read, so nothing claims they could not.
    expect(within(dialog).queryByRole("alert")).not.toBeInTheDocument();
    unmount();

    rights.write = false;
    render(<DocumentsTodoPage />);
    expect(screen.getByText("Put away 12 Black Beans")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Put away" }),
    ).not.toBeInTheDocument();
  });

  it("says the locations could not be loaded rather than offering none", async () => {
    server.use(
      http.get("/api/v1/locations", () =>
        HttpResponse.json({ detail: "down" }, { status: 500 }),
      ),
    );
    answer(
      queue([
        task({
          key: "putaway:line-3",
          kind: "putaway",
          source_kind: "putaway",
          source_id: "line-3",
          next_action: "put_away",
          subject: "Black Beans",
          count: "12",
          place: null,
          place_id: null,
        }),
      ]),
    );
    render(<DocumentsTodoPage />);

    await userEvent.click(screen.getByRole("button", { name: "Put away" }));
    const dialog = screen.getByRole("dialog", { name: "Put away" });
    expect(await within(dialog).findByRole("alert")).toBeInTheDocument();
    expect(
      within(dialog).getByRole("button", { name: /try again/i }),
    ).toBeInTheDocument();
  });

  it("opens a count that is under way instead of starting it again", async () => {
    answer(
      queue([
        task({
          key: "cycle_count:count-2",
          kind: "count",
          state: "in_progress",
          source_kind: "cycle_count",
          source_id: "count-2",
          next_action: "count",
          action_href: "/inventory/stock-takes/take-2/counting",
          subject: "Slow movers",
          document_type: null,
          document_status: null,
        }),
      ]),
    );
    render(<DocumentsTodoPage />);

    await userEvent.click(screen.getByRole("button", { name: "Count" }));

    expect(mutations.startCount).not.toHaveBeenCalled();
    expect(navigateMock).toHaveBeenLastCalledWith(
      "/inventory/stock-takes/take-2/counting",
    );
  });

  it("opens an open session where it was started, and completion on the document", async () => {
    answer(
      queue([
        task({
          key: "document:in-1",
          kind: "receive",
          source_id: "in-1",
          state: "in_progress",
          next_action: "resume",
          document_type: "IN",
          stage_holder_name: "Ann",
        }),
        task({
          key: "document:out-2",
          source_id: "out-2",
          state: "in_progress",
          next_action: "complete",
          number: "WZ/2",
        }),
      ]),
    );
    render(<DocumentsTodoPage />);

    expect(screen.getByText("In progress · Ann")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Resume" }));
    expect(navigateMock).toHaveBeenLastCalledWith(
      "/warehouse/documents/in-1#receive",
    );
    await userEvent.click(screen.getByRole("button", { name: "Complete" }));
    expect(navigateMock).toHaveBeenLastCalledWith("/warehouse/documents/out-2");
  });

  it("lists a task a module contributed, with the module's own words and link", async () => {
    answer(
      queue([
        task({
          key: "certificate_check:cert-1",
          kind: "certificate_check",
          source_kind: "certificate_check",
          source_id: "cert-1",
          next_action: null,
          sentence: "Check the delivery certificate for ZK/7",
          action_label: "Open certificate",
          action_href: "/certificates/7",
          subject: null,
          number: null,
          count: null,
          document_type: null,
          document_status: null,
        }),
      ]),
    );
    render(<DocumentsTodoPage />);

    expect(
      screen.getByText("Check the delivery certificate for ZK/7"),
    ).toBeInTheDocument();
    await userEvent.click(
      screen.getByRole("button", { name: "Open certificate" }),
    );
    expect(navigateMock).toHaveBeenLastCalledWith("/certificates/7");
  });

  it("asks the server for the reader's own and for the overdue tasks", async () => {
    const mine = task({
      key: "document:a",
      source_id: "a",
      number: "WZ/A",
      assignee_id: "user-me",
      subject: "Mine Ltd",
    });
    const late = task({
      key: "document:b",
      source_id: "b",
      number: "WZ/B",
      subject: "Ann Ltd",
      overdue: true,
      due_date: "2026-01-01",
    });
    const everything = [
      mine,
      late,
      task({ key: "document:c", source_id: "c", subject: "Nobody Ltd" }),
    ];
    vi.mocked(todoHooks.useDocumentsTodo).mockImplementation(
      ({ view } = {}) =>
        ({
          data: queue(
            view === "mine" ? [mine] : view === "overdue" ? [late] : everything,
          ),
          isLoading: false,
          isError: false,
          refetch: vi.fn(),
        }) as unknown as ReturnType<typeof todoHooks.useDocumentsTodo>,
    );
    render(<DocumentsTodoPage />);

    expect(screen.getByText(/Mine Ltd/)).toBeInTheDocument();
    expect(screen.getByText(/Ann Ltd/)).toBeInTheDocument();
    expect(screen.getByText(/Nobody Ltd/)).toBeInTheDocument();

    await userEvent.click(screen.getByRole("tab", { name: "Mine" }));
    expect(todoHooks.useDocumentsTodo).toHaveBeenLastCalledWith({
      limit: 100,
      view: "mine",
    });
    expect(screen.getByText(/Mine Ltd/)).toBeInTheDocument();
    expect(screen.queryByText(/Ann Ltd/)).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole("tab", { name: "Overdue" }));
    expect(todoHooks.useDocumentsTodo).toHaveBeenLastCalledWith({
      limit: 100,
      view: "overdue",
    });
    expect(screen.getByText(/Ann Ltd/)).toBeInTheDocument();
    expect(screen.getByText(/^Overdue since /)).toBeInTheDocument();
    expect(screen.queryByText(/Mine Ltd/)).not.toBeInTheDocument();
  });

  it("says so when a filter leaves nothing, and keeps the tabs", async () => {
    vi.mocked(todoHooks.useDocumentsTodo).mockImplementation(
      ({ view } = {}) =>
        ({
          data: queue(view === "mine" ? [] : [task()]),
          isLoading: false,
          isError: false,
          refetch: vi.fn(),
        }) as unknown as ReturnType<typeof todoHooks.useDocumentsTodo>,
    );
    render(<DocumentsTodoPage />);

    await userEvent.click(screen.getByRole("tab", { name: "Mine" }));
    expect(screen.getByText("Nothing is given to you.")).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "All" })).toBeInTheDocument();
  });

  it("shows the server's total, not the rows on screen", async () => {
    answer(queue([task()], {}, 130));
    render(<DocumentsTodoPage />);

    expect(screen.getByText("Showing 1 of 130")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Show more" }));
    expect(todoHooks.useDocumentsTodo).toHaveBeenLastCalledWith({
      limit: 200,
      view: "all",
    });
  });

  it("stops offering more at the most the server lists", async () => {
    answer(queue([task()], {}, 5000));
    render(<DocumentsTodoPage />);

    for (let page = 0; page < 9; page += 1) {
      await userEvent.click(screen.getByRole("button", { name: "Show more" }));
    }

    expect(todoHooks.useDocumentsTodo).toHaveBeenLastCalledWith({
      limit: todoHooks.MAX_TASKS,
      view: "all",
    });
    expect(screen.getByText("Showing 1 of 5000")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Show more" }),
    ).not.toBeInTheDocument();
  });

  it("gives a task to a person and back to nobody", async () => {
    answer(queue([task({ assignee_id: "user-ann" })]));
    render(<DocumentsTodoPage />);

    const select = screen.getByRole("combobox", {
      name: /Give to someone: Deliver order for Bistro Lato/,
    });
    expect(select).toHaveValue("user-ann");
    await userEvent.selectOptions(select, "user-me");
    expect(mutations.assign).toHaveBeenLastCalledWith({
      sourceKind: "document",
      sourceId: "doc-1",
      assigneeId: "user-me",
    });
    await userEvent.selectOptions(select, "");
    expect(mutations.assign).toHaveBeenLastCalledWith({
      sourceKind: "document",
      sourceId: "doc-1",
      assigneeId: null,
    });
  });

  it("adds a custom task, ticks it off and deletes it", async () => {
    answer(
      queue([
        task({
          key: "custom:c-1",
          kind: "custom",
          source_kind: "custom",
          source_id: "c-1",
          next_action: null,
          subject: "Move the rack",
          number: null,
          count: null,
          document_type: null,
          document_status: null,
        }),
      ]),
    );
    render(<DocumentsTodoPage />);

    expect(screen.getByText("Move the rack")).toBeInTheDocument();
    await userEvent.click(
      screen.getByRole("checkbox", { name: "Mark as done: Move the rack" }),
    );
    expect(mutations.done).toHaveBeenLastCalledWith({ id: "c-1", done: true });
    await userEvent.click(
      screen.getByRole("button", { name: "Delete task: Move the rack" }),
    );
    expect(mutations.remove).toHaveBeenLastCalledWith("c-1");

    await userEvent.type(
      screen.getByLabelText("New task"),
      "  Wash the floor ",
    );
    await userEvent.click(screen.getByRole("button", { name: "Add" }));
    expect(mutations.create).toHaveBeenLastCalledWith(
      { title: "Wash the floor", due_date: null },
      expect.anything(),
    );
  });

  it("does not add a task with no title", () => {
    answer(queue([task()]));
    render(<DocumentsTodoPage />);

    expect(screen.getByRole("button", { name: "Add" })).toBeDisabled();
  });

  it("offers the replenishment action only to who may also write orders", () => {
    const replenish = task({
      key: "replenishment:rule-1",
      kind: "replenish",
      source_kind: "replenishment",
      source_id: "rule-1",
      next_action: "replenish",
    });
    answer(queue([replenish]));
    const { unmount } = render(<DocumentsTodoPage />);
    expect(
      screen.getByRole("button", { name: "Replenish" }),
    ).toBeInTheDocument();
    unmount();

    rights.orders = false;
    render(<DocumentsTodoPage />);
    expect(
      screen.queryByRole("button", { name: "Replenish" }),
    ).not.toBeInTheDocument();
  });

  it("offers a read-only account none of the four action tiles", () => {
    rights.write = false;
    answer(queue([task()]));
    render(<DocumentsTodoPage />);

    for (const name of [/Receive goods/, /Issue goods/, /Move/, "Count"]) {
      expect(screen.queryByRole("button", { name })).not.toBeInTheDocument();
    }
  });

  it("offers a read-only account no way to act on documents, assign or add", () => {
    rights.write = false;
    answer(
      queue([
        task({ assignee_id: "user-ann", assignee_name: "Ann" }),
        task({
          key: "document:appr-1",
          kind: "approve",
          source_id: "appr-1",
          next_action: "review_approval",
          number: "PZ/9",
        }),
      ]),
    );
    render(<DocumentsTodoPage />);

    expect(
      screen.queryByRole("button", { name: "Pick" }),
    ).not.toBeInTheDocument();
    expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("New task")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Select WZ/1")).not.toBeInTheDocument();
    expect(screen.getByText("Ann")).toBeInTheDocument();
    // An approval the queue named is the reader's to decide.
    expect(
      screen.getByRole("button", { name: "Review approval" }),
    ).toBeInTheDocument();
  });

  it("lists a quarantine hold, opening its batch", async () => {
    answer(
      queue([], {
        quarantine: {
          items: [
            {
              lot_id: "lot-1",
              name: "LOT-41/26",
              product_name: "Milk",
              quantity: "8",
              uom_symbol: "pcs",
              reason: "Supplier notice 41/26",
            },
          ],
          total: 1,
        },
      }),
    );
    render(<DocumentsTodoPage />);

    expect(screen.getByText("Quarantine holds")).toBeInTheDocument();
    expect(screen.getByText("Milk")).toBeInTheDocument();
    expect(screen.getByText("8 pcs.")).toBeInTheDocument();
    expect(screen.getByText("Held: Supplier notice 41/26")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "LOT-41/26" })).toHaveAttribute(
      "href",
      "/inventory/lots/lot-1",
    );

    await userEvent.click(screen.getByRole("button", { name: "Review hold" }));
    expect(navigateMock).toHaveBeenLastCalledWith("/inventory/lots/lot-1");
  });

  it("opens a receipt's batchless hold on the shelf that holds it", async () => {
    answer(
      queue([], {
        quarantine: {
          items: [
            {
              lot_id: null,
              document_id: "in-9",
              document_number: "PZ/9",
              product_template_id: "tpl-1",
              item_id: "item-1",
              name: "PZ/9",
              product_name: "Milk",
              quantity: "3",
              uom_symbol: "pcs",
              reason: "Supplier notice 41/26",
              location_id: "q-1",
              location_name: "Quarantine shelf",
            },
          ],
          total: 1,
        },
      }),
    );
    render(<DocumentsTodoPage />);

    // The receipt that placed the goods is the row's name; the batchless
    // hold has no batch page to open.
    expect(screen.getByRole("link", { name: "PZ/9" })).toHaveAttribute(
      "href",
      "/warehouse/documents/in-9",
    );
    expect(screen.getByText("Milk")).toBeInTheDocument();
    expect(screen.getByText("3 pcs.")).toBeInTheDocument();
    expect(screen.getByText("Held: Supplier notice 41/26")).toBeInTheDocument();
    expect(screen.getByText("On Quarantine shelf")).toBeInTheDocument();

    // Both decisions are the same form the document register uses, opened
    // on the shelf the goods stand on: a transfer releases them, a scrap
    // writes them off.
    await userEvent.click(
      screen.getByRole("button", { name: "Move with a transfer" }),
    );
    expect(formStub.props).toMatchObject({
      initialType: "INT",
      initialSourceLocationId: "q-1",
      initialLines: [
        {
          item_id: "item-1",
          product_template_id: "tpl-1",
          name: "Milk",
          quantity: "3",
        },
      ],
    });

    // A write-off is one question — why — and one press: no office form,
    // no draft to post afterwards.
    let posted: Record<string, unknown> | null = null;
    server.use(
      http.post("/api/v1/warehouse/documents/post", async ({ request }) => {
        posted = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json({ id: "zl-1", number: "ZL/1" });
      }),
    );
    await userEvent.click(screen.getByRole("button", { name: "Write off" }));
    const dialog = await screen.findByRole("dialog");
    await userEvent.selectOptions(
      within(dialog).getByTestId("hold-write-off-reason-code"),
      "DAMAGED",
    );
    await userEvent.click(
      within(dialog).getByRole("button", { name: "Write off" }),
    );
    await waitFor(() =>
      expect(posted).toMatchObject({
        type: "SCRAP",
        source_location_id: "q-1",
        reason_code: "DAMAGED",
        lines: [{ item_id: "item-1", expected_quantity: 3 }],
      }),
    );
  });

  it("does not say a write-off happened while the document awaits approval", async () => {
    answer(
      queue([], {
        quarantine: {
          items: [
            {
              lot_id: null,
              document_id: "in-9",
              document_number: "PZ/9",
              product_template_id: "tpl-1",
              item_id: "item-1",
              name: "PZ/9",
              product_name: "Tea",
              quantity: "2",
              uom_symbol: "pcs",
              reason: "DAMAGE",
              location_id: "q-1",
              location_name: "Quarantine shelf",
            },
          ],
          total: 1,
        },
      }),
    );
    server.use(
      http.post("/api/v1/warehouse/documents/post", () =>
        HttpResponse.json({
          id: "zl-1",
          number: "ZL/1",
          status: "PENDING_APPROVAL",
        }),
      ),
    );
    render(<DocumentsTodoPage />);

    await userEvent.click(screen.getByRole("button", { name: "Write off" }));
    const dialog = await screen.findByRole("dialog");
    await userEvent.click(
      within(dialog).getByRole("button", { name: "Write off" }),
    );

    await waitFor(() =>
      expect(toast.success).toHaveBeenCalledWith("Document sent for approval"),
    );
    expect(toast.success).not.toHaveBeenCalledWith(
      expect.stringContaining("Wrote off"),
    );
  });

  it("names a receipt hold's reason in words, not as its stored code", () => {
    answer(
      queue([], {
        quarantine: {
          items: [
            {
              lot_id: null,
              document_id: "in-9",
              document_number: "PZ/9",
              product_template_id: "tpl-1",
              item_id: "item-1",
              name: "PZ/9",
              product_name: "Tea",
              quantity: "2",
              uom_symbol: "pcs",
              reason: "DAMAGE",
              location_id: "q-1",
              location_name: "Quarantine shelf",
            },
          ],
          total: 1,
        },
      }),
    );
    render(<DocumentsTodoPage />);

    expect(screen.getByText("Held: Damage")).toBeInTheDocument();
    expect(screen.queryByText("Held: DAMAGE")).not.toBeInTheDocument();
  });

  it("keeps the quarantine block when there are no tasks", () => {
    answer(
      queue([], {
        quarantine: {
          items: [{ lot_id: "lot-1", name: "LOT-41/26", quantity: "8" }],
          total: 1,
        },
      }),
    );
    render(<DocumentsTodoPage />);

    expect(screen.getByText("Quarantine holds")).toBeInTheDocument();
    expect(screen.queryByText("Nothing waiting")).not.toBeInTheDocument();
  });

  it("offers a read-only account no quarantine action", () => {
    rights.write = false;
    answer(
      queue([], {
        quarantine: {
          items: [
            {
              lot_id: "lot-1",
              name: "LOT-41/26",
              quantity: "8",
              uom_symbol: "pcs",
            },
            {
              lot_id: null,
              document_id: "in-9",
              name: "PZ/9",
              quantity: "3",
              uom_symbol: "pcs",
              location_id: "q-1",
            },
          ],
          total: 2,
        },
      }),
    );
    render(<DocumentsTodoPage />);

    expect(
      screen.queryByRole("button", { name: "Review hold" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Move with a transfer" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Write off" }),
    ).not.toBeInTheDocument();
  });

  it("says there is nothing waiting when there is nothing to do", () => {
    answer(queue([]));
    render(<DocumentsTodoPage />);

    expect(screen.getByText("Nothing waiting")).toBeInTheDocument();
  });

  it("says the warehouse is empty on a phone only when nothing at all waits", () => {
    viewport({ phone: true });
    answer(queue([]));
    render(<DocumentsTodoPage />);

    expect(screen.getByText("Nothing waiting")).toBeInTheDocument();
  });

  it("says nothing is given to the reader when only their own list is empty", async () => {
    viewport({ phone: true });
    vi.mocked(todoHooks.useDocumentsTodo).mockImplementation(
      ({ view } = {}) =>
        ({
          data: queue(view === "mine" ? [] : [task()]),
          isLoading: false,
          isError: false,
          refetch: vi.fn(),
        }) as unknown as ReturnType<typeof todoHooks.useDocumentsTodo>,
    );
    render(<DocumentsTodoPage />);

    await userEvent.click(screen.getByRole("tab", { name: "Mine" }));

    expect(screen.getByText("Nothing is given to you.")).toBeInTheDocument();
    expect(screen.queryByText("Nothing waiting")).not.toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "All" })).toBeInTheDocument();
  });

  describe("picking several dispatches at once", () => {
    const tasks = () => [
      task({
        key: "document:in-1",
        source_id: "in-1",
        kind: "receive",
        document_type: "IN",
        number: "PZ/1",
      }),
      task({ key: "document:out-1", source_id: "out-1", number: "WZ/1" }),
      task({
        key: "document:out-2",
        source_id: "out-2",
        number: "MM/2",
        document_type: "INTERNAL_OUT",
      }),
      task({
        key: "document:out-3",
        source_id: "out-3",
        number: "WZ/3",
        document_status: "DRAFT",
      }),
    ];

    it("offers no tick on the approval row of a dispatch that also waits to be picked", async () => {
      answer(
        queue([
          task({ key: "document:doc-1:ship" }),
          task({
            key: "document:doc-1:approve",
            kind: "approve",
            next_action: "review_approval",
          }),
        ]),
      );
      render(<DocumentsTodoPage />);

      await userEvent.click(screen.getByLabelText("Select WZ/1"));

      expect(screen.getAllByLabelText("Select WZ/1")).toHaveLength(1);
      expect(
        screen.getByRole("button", { name: "Pick 1 selected" }),
      ).toBeInTheDocument();
    });

    it("starts one session over the ticked dispatches, in list order", async () => {
      answer(queue(tasks()));
      render(<DocumentsTodoPage />);

      await userEvent.click(screen.getByLabelText("Select MM/2"));
      await userEvent.click(screen.getByLabelText("Select WZ/1"));
      await userEvent.click(
        screen.getByRole("button", { name: "Pick 2 selected" }),
      );

      expect(screen.getByTestId("picking-session")).toHaveTextContent(
        "out-1,out-2",
      );
    });

    it("keeps the pick bar clear of the phone's bottom navigation", async () => {
      // jsdom has no layout to measure; what can be checked is that the bar
      // is offset by the navigation's height the way every other sticky
      // footer is, and not pinned 0.5rem from the viewport's edge.
      answer(queue(tasks()));
      render(<DocumentsTodoPage />);

      await userEvent.click(screen.getByLabelText("Select WZ/1"));

      const bar = screen.getByText("1 selected").closest(".sticky");
      expect(bar?.className).toContain("--mobile-nav-height");
      expect(bar?.className).toContain("safe-area-inset-bottom");
    });

    it("makes the tick a 44 px target with a label around the box", () => {
      answer(queue(tasks()));
      render(<DocumentsTodoPage />);

      const label = screen.getByLabelText("Select WZ/1").closest("label");
      expect(label).toHaveClass("h-11", "w-11");
    });

    it("forgets a tick whose row the list no longer shows", async () => {
      vi.mocked(todoHooks.useDocumentsTodo).mockImplementation(
        ({ view } = {}) =>
          ({
            data: queue(
              view === "mine"
                ? [
                    task({
                      key: "document:out-1",
                      source_id: "out-1",
                      number: "WZ/1",
                    }),
                  ]
                : [
                    task({
                      key: "document:out-1",
                      source_id: "out-1",
                      number: "WZ/1",
                    }),
                    task({
                      key: "document:out-2",
                      source_id: "out-2",
                      number: "MM/2",
                      document_type: "INTERNAL_OUT",
                    }),
                  ],
            ),
            isLoading: false,
            isError: false,
            refetch: vi.fn(),
          }) as unknown as ReturnType<typeof todoHooks.useDocumentsTodo>,
      );
      render(<DocumentsTodoPage />);

      await userEvent.click(screen.getByLabelText("Select MM/2"));
      await userEvent.click(screen.getByRole("tab", { name: "Mine" }));
      await userEvent.click(screen.getByRole("tab", { name: "All" }));

      // The row the reader left off the screen does not come back ticked:
      // the bar and the session are about the list in view.
      expect(screen.getByLabelText("Select MM/2")).not.toBeChecked();
      expect(
        screen.queryByRole("button", { name: /Pick \d+ selected/ }),
      ).not.toBeInTheDocument();
    });

    it("names the approval a blocked dispatch needs and does not tick it", () => {
      answer(
        queue([
          task({
            key: "document:out-4",
            source_id: "out-4",
            number: "WZ/4",
            next_action: "request_approval",
          }),
        ]),
      );
      render(<DocumentsTodoPage />);

      // The queue must not promise a pick the picking session refuses; the
      // row sends the reader to the dialog that raises the request instead.
      expect(
        screen.getByRole("button", { name: "Request approval" }),
      ).toBeInTheDocument();
      expect(screen.queryByLabelText("Select WZ/4")).not.toBeInTheDocument();
    });

    it("offers the tick only on dispatches that can be picked", () => {
      answer(queue(tasks()));
      render(<DocumentsTodoPage />);

      expect(screen.getByLabelText("Select WZ/1")).toBeInTheDocument();
      expect(screen.getByLabelText("Select MM/2")).toBeInTheDocument();
      expect(screen.queryByLabelText("Select WZ/3")).not.toBeInTheDocument();
      expect(screen.queryByLabelText("Select PZ/1")).not.toBeInTheDocument();
      expect(
        screen.queryByRole("button", { name: /Pick \d+ selected/ }),
      ).not.toBeInTheDocument();
    });
  });
});
