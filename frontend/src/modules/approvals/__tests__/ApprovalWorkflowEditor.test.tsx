import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { toast } from "sonner";
import { ApprovalWorkflowEditor } from "../components/ApprovalWorkflowEditor";
import { server } from "@/test/mocks/server";
import { http, HttpResponse } from "msw";
import type { StageDraft } from "../workflowStages";
import { onePage } from "@/test/mocks/page";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn(), info: vi.fn() },
}));

const members = [
  {
    id: "u-1",
    email: "alice@example.com",
    full_name: "Alice",
    role: "admin",
    is_active: true,
  },
  {
    id: "u-2",
    email: "bob@example.com",
    full_name: "Bob",
    role: "manager",
    is_active: true,
  },
  {
    id: "u-3",
    email: "carol@example.com",
    full_name: null,
    role: "user",
    is_active: true,
  },
  {
    id: "u-4",
    email: "dave@example.com",
    full_name: "Dave",
    role: "manager",
    is_active: true,
  },
  {
    id: "u-5",
    email: "erin@example.com",
    full_name: "Erin",
    role: "manager",
    is_active: false,
  },
];

const roles = [
  {
    id: "r-manager",
    organization_id: null,
    name: "manager",
    is_system: true,
    permissions: ["approvals:approve"],
    member_count: 3,
  },
  {
    id: "r-store",
    organization_id: "o-1",
    name: "Storeman",
    is_system: false,
    permissions: ["approvals:read"],
    member_count: 2,
  },
];

beforeEach(() => {
  vi.clearAllMocks();
  server.resetHandlers();
  server.use(
    http.get("/api/v1/users/org-members", () =>
      HttpResponse.json(onePage(members)),
    ),
    http.get("/api/v1/roles", () => HttpResponse.json(onePage(roles))),
  );
});

const createWrapper = () => {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
};

const named = (overrides: Partial<StageDraft> = {}): StageDraft => ({
  order: 1,
  label: "Manager Review",
  approver_user_ids: ["u-1"],
  open: false,
  ...overrides,
});

const open = (overrides: Partial<StageDraft> = {}): StageDraft => ({
  order: 1,
  label: "Anyone",
  approver_user_ids: [],
  open: true,
  ...overrides,
});

function renderEditor(stages: StageDraft[], onChange = vi.fn()) {
  render(<ApprovalWorkflowEditor stages={stages} onChange={onChange} />, {
    wrapper: createWrapper(),
  });
  return onChange;
}

const lastStages = (onChange: ReturnType<typeof vi.fn>) =>
  onChange.mock.calls.at(-1)![0] as StageDraft[];

async function chooseRole(name: string) {
  await userEvent.click(
    await screen.findByRole("combobox", { name: "Add everyone with a role" }),
  );
  await userEvent.click(await screen.findByRole("option", { name }));
}

describe("ApprovalWorkflowEditor", () => {
  it("renders one card per stage", () => {
    renderEditor([
      open({ order: 1, label: "A" }),
      open({ order: 2, label: "B" }),
    ]);
    expect(screen.getByDisplayValue("A")).toBeInTheDocument();
    expect(screen.getByDisplayValue("B")).toBeInTheDocument();
  });

  it("appends a stage that names people, with order = max+1", () => {
    const onChange = renderEditor([
      open({ order: 1, label: "A" }),
      open({ order: 5, label: "B" }),
    ]);
    fireEvent.click(screen.getByText("Add Stage"));
    const added = lastStages(onChange)[2];
    expect(added).toEqual({
      order: 6,
      label: "Stage 6",
      approver_user_ids: [],
      open: false,
    });
  });

  it("starts the order at 1 when no stages exist", () => {
    const onChange = renderEditor([]);
    fireEvent.click(screen.getByText("Add Stage"));
    expect(lastStages(onChange)[0].order).toBe(1);
  });

  it("updates the stage label when the input changes", () => {
    const onChange = renderEditor([named()]);
    fireEvent.change(screen.getByDisplayValue("Manager Review"), {
      target: { value: "Director Review" },
    });
    expect(lastStages(onChange)[0].label).toBe("Director Review");
  });

  it("has no role field: a stage is its name and who decides it", () => {
    renderEditor([named()]);
    expect(
      screen.queryByRole("combobox", { name: /^Role$/ }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole("combobox", { name: "Who decides" }),
    ).toHaveTextContent("People named");
  });

  it("opening a stage to anyone with the permission clears the people named", async () => {
    const onChange = renderEditor([
      named({ approver_user_ids: ["u-1", "u-2"] }),
    ]);
    await userEvent.click(
      screen.getByRole("combobox", { name: "Who decides" }),
    );
    await userEvent.click(
      await screen.findByRole("option", {
        name: "Anyone who may approve",
      }),
    );
    expect(lastStages(onChange)[0]).toMatchObject({
      open: true,
      approver_user_ids: [],
    });
  });

  it("an open stage shows no approver list, and naming people asks for one", async () => {
    const onChange = renderEditor([open()]);
    expect(
      screen.queryByRole("group", { name: "Approvers" }),
    ).not.toBeInTheDocument();

    await userEvent.click(
      screen.getByRole("combobox", { name: "Who decides" }),
    );
    await userEvent.click(
      await screen.findByRole("option", { name: "People named" }),
    );
    expect(lastStages(onChange)[0]).toMatchObject({
      open: false,
      approver_user_ids: [],
    });
  });

  it("a stage that names nobody yet says so", () => {
    renderEditor([named({ approver_user_ids: [] })]);
    expect(
      screen.getByRole("group", { name: "Approvers" }),
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        "Name at least one person, or let anyone with the approve permission decide.",
      ),
    ).toBeInTheDocument();
  });

  it("adds everyone active at a built-in level, skipping who is already named", async () => {
    const onChange = renderEditor([named({ approver_user_ids: ["u-2"] })]);
    await chooseRole("Manager");
    // Bob was named already, Erin is not active: Dave alone is added.
    expect(lastStages(onChange)[0].approver_user_ids).toEqual(["u-2", "u-4"]);
    expect(lastStages(onChange)[0]).not.toHaveProperty("role");
  });

  it("adds the holders of an organization's own role, asked from the server", async () => {
    server.use(
      http.get("/api/v1/roles/r-store/members", () =>
        HttpResponse.json(
          onePage([
            { id: "u-3", email: "carol@example.com", full_name: null },
            { id: "u-5", email: "erin@example.com", full_name: "Erin" },
          ]),
        ),
      ),
    );
    const onChange = renderEditor([named({ approver_user_ids: [] })]);
    await chooseRole("Storeman");
    await waitFor(() =>
      expect(lastStages(onChange)[0].approver_user_ids).toEqual(["u-3"]),
    );
  });

  it("says so when a role brings nobody new", async () => {
    const onChange = renderEditor([
      named({ approver_user_ids: ["u-2", "u-4"] }),
    ]);
    await chooseRole("Manager");
    expect(onChange).not.toHaveBeenCalled();
    expect(toast.info).toHaveBeenCalledWith(
      "Nobody new to add — everyone active with the role “Manager” is already named.",
    );
  });

  it("offers no role shortcut when the roles list is closed to the reader", async () => {
    let rolesFetched = 0;
    server.use(
      http.get("/api/v1/roles", () => {
        rolesFetched += 1;
        return new HttpResponse(null, { status: 403 });
      }),
    );
    renderEditor([named({ approver_user_ids: [] })]);
    await waitFor(() => expect(rolesFetched).toBeGreaterThan(0));
    expect(
      screen.queryByRole("combobox", { name: "Add everyone with a role" }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole("group", { name: "Approvers" }),
    ).toBeInTheDocument();
  });

  it("offers no role shortcut when the member list failed to load", async () => {
    let membersFetched = 0;
    server.use(
      http.get("/api/v1/users/org-members", () => {
        membersFetched += 1;
        return new HttpResponse(null, { status: 500 });
      }),
    );
    renderEditor([named({ approver_user_ids: [] })]);
    await screen.findByRole("group", { name: "Approvers" });
    await waitFor(() => expect(membersFetched).toBeGreaterThan(0));
    await waitFor(() =>
      expect(
        screen.queryByRole("combobox", { name: "Add everyone with a role" }),
      ).not.toBeInTheDocument(),
    );
  });

  it("warns when nobody in the organization holds the approve grant", async () => {
    // An open stage is decided by anyone holding approvals:approve. The
    // server refuses a workflow whose stage nobody could decide; the form
    // says so while the stage is being written, from the counts and grants
    // the roles payload carries.
    server.use(
      http.get("/api/v1/roles", () =>
        HttpResponse.json(
          onePage([
            {
              id: "r-1",
              organization_id: "o-1",
              name: "user",
              is_system: false,
              permissions: ["warehouse:read"],
              member_count: 3,
            },
          ]),
        ),
      ),
    );
    renderEditor([open()]);
    expect(
      await screen.findByText(/holds the approvals approve permission/i),
    ).toBeInTheDocument();
  });

  it("says nothing about approvers when somebody holds the grant", async () => {
    let rolesFetched = 0;
    server.use(
      http.get("/api/v1/roles", () => {
        rolesFetched += 1;
        return HttpResponse.json(onePage(roles));
      }),
    );
    renderEditor([open()]);
    // Wait for the payload the warning is built from, so the absence below
    // is about the rule and not about a query still in flight.
    await waitFor(() => expect(rolesFetched).toBeGreaterThan(0));
    expect(
      screen.queryByText(/holds the approvals approve permission/i),
    ).not.toBeInTheDocument();
  });

  it("removes a stage on the trash button click", () => {
    const onChange = renderEditor([
      open({ order: 1, label: "A" }),
      open({ order: 2, label: "B" }),
    ]);
    fireEvent.click(screen.getAllByLabelText("Remove stage")[0]);
    const after = lastStages(onChange);
    expect(after).toHaveLength(1);
    expect(after[0].label).toBe("B");
  });

  it("never submits the surrounding form from a stage control", () => {
    const onSubmit = vi.fn((e: React.FormEvent) => e.preventDefault());
    render(
      <form onSubmit={onSubmit}>
        <ApprovalWorkflowEditor stages={[open()]} onChange={vi.fn()} />
      </form>,
      { wrapper: createWrapper() },
    );
    fireEvent.click(screen.getByText("Add Stage"));
    fireEvent.click(screen.getByLabelText("Remove stage"));
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("puts who decides beside the label, the approvers below", () => {
    renderEditor([named({ label: "Lead" })]);
    const header = screen.getByTestId("stage-header-1");
    const deciders = screen.getByRole("combobox", { name: "Who decides" });
    // The label and the choice share one row with the handle and the bin.
    expect(header).toContainElement(screen.getByDisplayValue("Lead"));
    expect(header).toContainElement(deciders);
    expect(header).toContainElement(screen.getByLabelText("Remove stage"));
    // DOCUMENT_POSITION_FOLLOWING: the approvers come after the choice.
    const approvers = screen.getByRole("group", { name: "Approvers" });
    expect(header).not.toContainElement(approvers);
    expect(
      deciders.compareDocumentPosition(approvers) &
        Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
  });
});
