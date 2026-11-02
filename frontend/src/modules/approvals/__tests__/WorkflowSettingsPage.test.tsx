import { describe, it, expect, vi, beforeEach } from "vitest";
import {
  act,
  render,
  screen,
  fireEvent,
  waitFor,
  within,
} from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import userEvent from "@testing-library/user-event";
import {
  BrowserRouter,
  Link,
  MemoryRouter,
  useLocation,
} from "react-router-dom";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { useNavLeaveGuard } from "@/hooks/useNavLeaveGuard";
import { useFormGuardStore } from "@/store/formGuardStore";
import WorkflowSettingsPage from "../pages/WorkflowSettingsPage";
import { AVAILABLE_TARGET_TYPES } from "../targetTypes";
import { server } from "@/test/mocks/server";
import { signInWith } from "@/test/auth";
import { http, HttpResponse } from "msw";
import * as modulesCtx from "@/contexts/ModulesContext";
import { onePage } from "@/test/mocks/page";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn(), warning: vi.fn() },
}));

// A stable spy, so a test can read what the page put in the page header —
// that is where the Create button lives.
const { setHeader } = vi.hoisted(() => ({ setHeader: vi.fn() }));

vi.mock("@/hooks/useModulePageHeader", () => ({
  useModulePageHeader: () => ({ setHeader }),
}));

// Every module that raises approval requests is on unless a test says
// otherwise: the target types the form offers follow them.
const ALL_REQUESTING_MODULES = [
  "approvals",
  "warehouse",
  "purchase_orders",
  "equipment",
];

beforeEach(() => {
  vi.spyOn(modulesCtx, "useModules").mockReturnValue({
    enabledModules: ALL_REQUESTING_MODULES,
    isModuleEnabled: (name: string) => ALL_REQUESTING_MODULES.includes(name),
    isLoading: false,
    refreshModules: vi.fn(),
    focusModule: null,
    hiddenModules: [],
  });
  vi.clearAllMocks();
  server.resetHandlers();
  // Silence MSW catch-all warnings from the UserMultiSelect fetches that
  // happen when the workflow editor renders the approver picker.
  server.use(orgMembersHandler, nothingWaiting);
  // Editing workflows is gated on the key the API enforces.
  signInWith(["approvals:configure"]);
});

const createWrapper = () => {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>{children}</BrowserRouter>
    </QueryClientProvider>
  );
};

const createQueryWrapper = () => {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
};

const baseWorkflow = {
  id: "wf-1",
  organization_id: "org-1",
  target_type: "document",
  name: "Document Approval",
  stages: [
    {
      order: 1,
      label: "Manager Review",
      approver_user_ids: [],
    },
  ],
  is_active: true,
  requester_scope: { everyone: true, user_ids: [], role_ids: [] },
  created_at: new Date().toISOString(),
  updated_at: null,
};

/** A new stage names people; these tests leave it to anyone with the grant. */
async function openTheStage() {
  await userEvent.click(screen.getByRole("combobox", { name: "Who decides" }));
  await userEvent.click(
    await screen.findByRole("option", {
      name: "Anyone who may approve",
    }),
  );
}

/** A workflow says whose submissions it holds before it can be saved. */
async function chooseEveryone() {
  await userEvent.click(
    screen.getByRole("combobox", { name: /Who it applies to/ }),
  );
  await userEvent.click(
    await screen.findByRole("option", { name: "Everyone" }),
  );
}

const nothingWaiting = http.get("/api/v1/approvals/workflows/:id/waiting", () =>
  HttpResponse.json({
    total: 0,
    waiting: [],
    settings_requiring_approval: [],
  }),
);

const orgMembersHandler = http.get("/api/v1/users/org-members", () =>
  HttpResponse.json(onePage([])),
);

describe("WorkflowSettingsPage", () => {
  it("renders empty state when there are no workflows", async () => {
    server.use(
      http.get("/api/v1/approvals/workflows", () =>
        HttpResponse.json(onePage([])),
      ),
    );
    render(<WorkflowSettingsPage />, { wrapper: createWrapper() });
    expect(
      await screen.findByText("No workflows configured"),
    ).toBeInTheDocument();
  });

  it("calls the filtered list a permission boundary, not an empty org", async () => {
    // GET /workflows answers a role holding neither approvals:read nor
    // :configure with a filtered 200 — always empty, whatever the
    // organization has. Calling that "no workflows configured" would be a
    // report the server never made.
    signInWith(["warehouse:read"]);
    server.use(
      http.get("/api/v1/approvals/workflows", () =>
        HttpResponse.json(onePage([])),
      ),
    );
    render(<WorkflowSettingsPage />, { wrapper: createWrapper() });
    expect(
      await screen.findByText("Workflow list unavailable"),
    ).toBeInTheDocument();
    expect(
      screen.queryByText("No workflows configured"),
    ).not.toBeInTheDocument();
  });

  it("renders one card per workflow", async () => {
    server.use(
      http.get("/api/v1/approvals/workflows", () =>
        HttpResponse.json(
          onePage([
            baseWorkflow,
            {
              ...baseWorkflow,
              id: "wf-2",
              name: "PO Approval",
              target_type: "purchase_order",
            },
          ]),
        ),
      ),
    );
    render(<WorkflowSettingsPage />, { wrapper: createWrapper() });
    expect(await screen.findByText("Document Approval")).toBeInTheDocument();
    expect(screen.getByText("PO Approval")).toBeInTheDocument();
  });

  it("shows the Inactive marker for inactive workflows", async () => {
    server.use(
      http.get("/api/v1/approvals/workflows", () =>
        HttpResponse.json(onePage([{ ...baseWorkflow, is_active: false }])),
      ),
    );
    render(<WorkflowSettingsPage />, { wrapper: createWrapper() });
    expect(await screen.findByText(/Inactive/)).toBeInTheDocument();
  });

  it("shows the Active marker for active workflows", async () => {
    server.use(
      http.get("/api/v1/approvals/workflows", () =>
        HttpResponse.json(onePage([baseWorkflow])),
      ),
    );
    render(<WorkflowSettingsPage />, { wrapper: createWrapper() });
    expect(await screen.findByText("Active")).toBeInTheDocument();
  });

  it("names a workflow whose stage nobody can decide", async () => {
    // The dead end belongs to the definition, and the list is where it can
    // still be fixed — the parked request only tells the next reader.
    server.use(
      http.get("/api/v1/approvals/workflows", () =>
        HttpResponse.json(
          onePage([
            {
              ...baseWorkflow,
              solvable: false,
              undecidable_reason: "named_approvers_cannot_decide",
            },
          ]),
        ),
      ),
    );
    render(<WorkflowSettingsPage />, { wrapper: createWrapper() });
    expect(
      await screen.findByText("A stage nobody can decide"),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/names approvers who cannot see approvals/i),
    ).toBeInTheDocument();
  });

  it("names the requests already parked on a dead-end workflow", async () => {
    server.use(
      http.get("/api/v1/approvals/workflows", () =>
        HttpResponse.json(
          onePage([
            {
              ...baseWorkflow,
              solvable: false,
              undecidable_reason: "named_approvers_cannot_decide",
              waiting_requests: [
                {
                  request_id: "req-1",
                  target_type: "document",
                  target_id: "doc-1",
                  label: "IN/2026/001",
                },
              ],
            },
          ]),
        ),
      ),
    );
    render(<WorkflowSettingsPage />, { wrapper: createWrapper() });
    const note = await screen.findByRole("note");
    expect(within(note).getByText(/Already waiting here/)).toBeInTheDocument();
    expect(
      within(note).getByRole("link", { name: "IN/2026/001" }),
    ).toHaveAttribute("href", "/warehouse/documents/doc-1");
  });

  it("names the other dead end the same way the request does", async () => {
    server.use(
      http.get("/api/v1/approvals/workflows", () =>
        HttpResponse.json(
          onePage([
            {
              ...baseWorkflow,
              solvable: false,
              undecidable_reason: "no_approver_in_organization",
            },
          ]),
        ),
      ),
    );
    render(<WorkflowSettingsPage />, { wrapper: createWrapper() });
    expect(
      await screen.findByText(/open to anyone holding the approve permission/i),
    ).toBeInTheDocument();
  });

  it("says nothing about a workflow whose stages can be decided", async () => {
    server.use(
      http.get("/api/v1/approvals/workflows", () =>
        HttpResponse.json(
          onePage([
            { ...baseWorkflow, solvable: true, undecidable_reason: null },
          ]),
        ),
      ),
    );
    render(<WorkflowSettingsPage />, { wrapper: createWrapper() });
    await screen.findByText("Document Approval");
    expect(
      screen.queryByText("A stage nobody can decide"),
    ).not.toBeInTheDocument();
  });

  it("hides the tip banner when no workflows exist", async () => {
    server.use(
      http.get("/api/v1/approvals/workflows", () =>
        HttpResponse.json(onePage([])),
      ),
    );
    render(<WorkflowSettingsPage />, { wrapper: createWrapper() });
    await screen.findByText("No workflows configured");
    expect(
      screen.queryByText(/only assigned approver/i),
    ).not.toBeInTheDocument();
  });

  it("shows named approvers on a stage", async () => {
    server.use(
      http.get("/api/v1/approvals/workflows", () =>
        HttpResponse.json(
          onePage([
            {
              ...baseWorkflow,
              stages: [
                {
                  order: 1,
                  label: "Manager Review",
                  approver_user_ids: ["u-1"],
                },
              ],
            },
          ]),
        ),
      ),
      http.get("/api/v1/users/org-members", () =>
        HttpResponse.json(
          onePage([
            { id: "u-1", full_name: "Alice Approver", email: "alice@x.com" },
          ]),
        ),
      ),
    );
    render(<WorkflowSettingsPage />, { wrapper: createWrapper() });
    expect(await screen.findByText(/Alice Approver/)).toBeInTheDocument();
  });

  it("says who decides a stage that names nobody, not a role it once carried", async () => {
    server.use(
      http.get("/api/v1/approvals/workflows", () =>
        HttpResponse.json(
          onePage([
            {
              ...baseWorkflow,
              stages: [{ order: 1, label: "Sign-off", approver_user_ids: [] }],
            },
          ]),
        ),
      ),
    );
    render(<WorkflowSettingsPage />, { wrapper: createWrapper() });
    expect(
      await screen.findByText("· Anyone who may approve"),
    ).toBeInTheDocument();
  });

  it("says the members could not be loaded instead of naming roles", async () => {
    server.use(
      http.get("/api/v1/approvals/workflows", () =>
        HttpResponse.json(onePage([baseWorkflow])),
      ),
      http.get(
        "/api/v1/users/org-members",
        () => new HttpResponse(null, { status: 500 }),
      ),
    );
    render(<WorkflowSettingsPage />, { wrapper: createWrapper() });
    expect(await screen.findByRole("alert")).toBeInTheDocument();
  });

  it("will not confirm a switch-off it could not check", async () => {
    server.use(
      http.get("/api/v1/approvals/workflows", () =>
        HttpResponse.json(onePage([baseWorkflow])),
      ),
      http.get(
        "/api/v1/approvals/workflows/:id/waiting",
        () => new HttpResponse(null, { status: 500 }),
      ),
    );
    render(<WorkflowSettingsPage />, { wrapper: createWrapper() });
    fireEvent.click(await screen.findByRole("button", { name: "Deactivate" }));
    const dialog = await screen.findByRole("alertdialog");
    await waitFor(() =>
      expect(dialog).toHaveTextContent("could not be checked"),
    );
    expect(
      within(dialog).getByRole("button", { name: "Deactivate" }),
    ).toBeDisabled();
  });

  it("toggles a workflow off via the Deactivate button", async () => {
    let receivedBody: Record<string, unknown> | null = null;
    server.use(
      http.get("/api/v1/approvals/workflows", () =>
        HttpResponse.json(onePage([baseWorkflow])),
      ),
      http.patch("/api/v1/approvals/workflows/:id", async ({ request }) => {
        receivedBody = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json({ ...baseWorkflow, ...receivedBody });
      }),
    );
    render(<WorkflowSettingsPage />, { wrapper: createWrapper() });
    fireEvent.click(await screen.findByRole("button", { name: "Deactivate" }));
    // Switching a workflow off asks first; nothing is sent until it is answered.
    const dialog = await screen.findByRole("alertdialog");
    expect(receivedBody).toBeNull();
    await waitFor(() =>
      expect(
        within(dialog).getByRole("button", { name: "Deactivate" }),
      ).toBeEnabled(),
    );
    fireEvent.click(within(dialog).getByRole("button", { name: "Deactivate" }));
    await waitFor(() => expect(receivedBody).not.toBeNull());
    expect(receivedBody).toEqual({ is_active: false });
  });

  it("says in numbers what waits on the workflow, and what still demands approval", async () => {
    server.use(
      http.get("/api/v1/approvals/workflows", () =>
        HttpResponse.json(onePage([baseWorkflow])),
      ),
      http.get("/api/v1/approvals/workflows/:id/waiting", () =>
        HttpResponse.json({
          total: 3,
          waiting: [
            { target_type: "document", count: 2 },
            { target_type: "purchase_order", count: 1 },
          ],
          settings_requiring_approval: ["approval_threshold"],
        }),
      ),
    );
    render(<WorkflowSettingsPage />, { wrapper: createWrapper() });
    fireEvent.click(await screen.findByRole("button", { name: "Deactivate" }));
    const dialog = await screen.findByRole("alertdialog");
    await waitFor(() =>
      expect(dialog).toHaveTextContent("Document: 2, Purchase Order: 1"),
    );
    expect(dialog).toHaveTextContent("go on without approval");
    expect(dialog).toHaveTextContent("the approval threshold");
    expect(dialog).toHaveTextContent("Released documents stop at completion");
  });

  it.each(["approval_required", "approval_threshold"])(
    "words an order workflow's %s as a limit on new orders, not a precondition of the release",
    async (setting) => {
      server.use(
        http.get("/api/v1/approvals/workflows", () =>
          HttpResponse.json(
            onePage([{ ...baseWorkflow, target_type: "purchase_order" }]),
          ),
        ),
        http.get("/api/v1/approvals/workflows/:id/waiting", () =>
          HttpResponse.json({
            total: 1,
            waiting: [{ target_type: "purchase_order", count: 1 }],
            settings_requiring_approval: [setting],
          }),
        ),
      );
      render(<WorkflowSettingsPage />, { wrapper: createWrapper() });
      fireEvent.click(
        await screen.findByRole("button", { name: "Deactivate" }),
      );
      const dialog = await screen.findByRole("alertdialog");
      await waitFor(() =>
        expect(dialog).toHaveTextContent("Released orders go on as confirmed"),
      );
      expect(dialog).toHaveTextContent("new orders cannot be confirmed");
      expect(dialog).not.toHaveTextContent("clear that setting first");
      expect(dialog).not.toHaveTextContent("Released documents stop");
    },
  );

  it("asks the same question before deleting, and says nothing of waiting when nothing waits", async () => {
    server.use(
      http.get("/api/v1/approvals/workflows", () =>
        HttpResponse.json(onePage([baseWorkflow])),
      ),
    );
    render(<WorkflowSettingsPage />, { wrapper: createWrapper() });
    fireEvent.click(
      (await screen.findAllByRole("button", { name: "Delete" }))[0],
    );
    const dialog = await screen.findByRole("alertdialog");
    await waitFor(() =>
      expect(dialog).toHaveTextContent("It leaves this list"),
    );
    expect(dialog).not.toHaveTextContent("Waiting on it now");
    expect(dialog).not.toHaveTextContent("Still requiring approval");
  });

  it("gives the card's actions one weight, edit first, delete past a divider", async () => {
    // The row mixed a boxed Edit with two bare red labels, so its three
    // buttons stood at three weights and read as misaligned. One weight for
    // all of them; the colour, not a box, marks what switches off or removes.
    server.use(
      http.get("/api/v1/approvals/workflows", () =>
        HttpResponse.json(
          onePage([
            baseWorkflow,
            {
              ...baseWorkflow,
              id: "wf-2",
              name: "PO Approval",
              target_type: "purchase_order",
              is_active: false,
            },
          ]),
        ),
      ),
    );
    render(<WorkflowSettingsPage />, { wrapper: createWrapper() });
    const boxed = (button: HTMLElement) =>
      button.className.split(/\s+/).includes("border");
    const danger = (button: HTMLElement) =>
      button.className.includes("text-on-danger");

    const on = within(await screen.findByTestId("workflow-actions-wf-1"));
    const onButtons = on.getAllByRole("button");
    expect(onButtons.map((b) => b.textContent)).toEqual([
      "Edit",
      "Deactivate",
      "Delete",
    ]);
    expect(onButtons.filter(boxed)).toEqual([]);
    expect(onButtons.map(danger)).toEqual([false, true, true]);
    const remove = on.getByRole("button", { name: "Delete" });
    expect(remove.previousElementSibling).toHaveClass("w-px");

    const off = within(screen.getByTestId("workflow-actions-wf-2"));
    const offButtons = off.getAllByRole("button");
    expect(offButtons.map((b) => b.textContent)).toEqual([
      "Edit",
      "Activate",
      "Delete",
    ]);
    expect(offButtons.filter(boxed)).toEqual([]);
    expect(offButtons.map(danger)).toEqual([false, false, true]);
  });

  it("opens the create form when the New button is clicked", async () => {
    server.use(
      http.get("/api/v1/approvals/workflows", () =>
        HttpResponse.json(onePage([])),
      ),
    );
    render(<WorkflowSettingsPage />, { wrapper: createWrapper() });
    await screen.findByText("No workflows configured");
    const createBtn = screen.getByRole("button", { name: "Create Workflow" });
    fireEvent.click(createBtn);
    expect(screen.getByTestId("workflow-name-input")).toBeInTheDocument();
  });

  it("opens the create form on arrival when sent here with ?new=1", async () => {
    server.use(
      http.get("/api/v1/approvals/workflows", () =>
        HttpResponse.json(onePage([])),
      ),
    );
    render(
      <MemoryRouter
        initialEntries={["/approvals/workflows?new=1&target=purchase_order"]}
      >
        <WorkflowSettingsPage />
      </MemoryRouter>,
      { wrapper: createQueryWrapper() },
    );
    expect(
      await screen.findByTestId("workflow-name-input"),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("combobox", { name: /Target type/ }),
    ).toHaveTextContent("Purchase Order");
  });

  it("does not open the form for a reader who may not configure", async () => {
    signInWith(["approvals:read"]);
    server.use(
      http.get("/api/v1/approvals/workflows", () =>
        HttpResponse.json(onePage([])),
      ),
    );
    render(
      <MemoryRouter initialEntries={["/approvals/workflows?new=1"]}>
        <WorkflowSettingsPage />
      </MemoryRouter>,
      { wrapper: createQueryWrapper() },
    );
    await screen.findByText("No workflows configured");
    expect(screen.queryByTestId("workflow-name-input")).toBeNull();
  });

  it("keeps the empty state's create out of the primary slot the header owns", async () => {
    // The header carries the view's one filled create button; the empty
    // state used to repeat it as a second filled one on the same screen
    // The entry stays — demoted, not removed — because the empty
    // state is where a first-time reader is looking.
    server.use(
      http.get("/api/v1/approvals/workflows", () =>
        HttpResponse.json(onePage([])),
      ),
    );
    render(<WorkflowSettingsPage />, { wrapper: createWrapper() });
    await screen.findByText("No workflows configured");

    const createBtn = screen.getByRole("button", { name: "Create Workflow" });
    expect(createBtn).not.toHaveClass("bg-primary-700");
  });

  /** The organization runs these modules besides approvals. */
  const withModules = (modules: string[]) => {
    const enabled = ["approvals", ...modules];
    vi.spyOn(modulesCtx, "useModules").mockReturnValue({
      enabledModules: enabled,
      isModuleEnabled: (name: string) => enabled.includes(name),
      isLoading: false,
      refreshModules: vi.fn(),
      focusModule: null,
      hiddenModules: [],
    });
  };

  /** The target types the create form's select offers, by value. */
  const offeredTargets = () => {
    const targetSelect = Array.from(document.querySelectorAll("select")).find(
      (select) =>
        Array.from(select.options).some((option) =>
          ["document", "purchase_order", "equipment_checkout"].includes(
            option.value,
          ),
        ),
    );
    return Array.from(targetSelect?.options ?? [])
      .map((option) => option.value)
      .filter(Boolean);
  };

  it("offers only the target types a switched-on module can raise", async () => {
    // A home organization: no warehouse, no purchase orders. A workflow for
    // documents or orders could be saved and switched on and never hold
    // anything, so the form does not offer them.
    withModules(["equipment"]);
    server.use(
      http.get("/api/v1/approvals/workflows", () =>
        HttpResponse.json(onePage([])),
      ),
    );
    render(<WorkflowSettingsPage />, { wrapper: createWrapper() });
    await screen.findByText("No workflows configured");
    fireEvent.click(screen.getByRole("button", { name: "Create Workflow" }));

    expect(offeredTargets()).toEqual(["equipment_checkout"]);
    expect(
      screen.getByRole("combobox", { name: /Target type/ }),
    ).toHaveTextContent("Equipment Checkout");
  });

  it("says no switched-on module asks for approvals, and saves nothing", async () => {
    // Nothing that raises requests is on: the form used to fall back to a
    // Document target it did not show, and saved a workflow guarding nothing.
    withModules([]);
    const posted = vi.fn();
    server.use(
      http.get("/api/v1/approvals/workflows", () =>
        HttpResponse.json(onePage([])),
      ),
      http.post("/api/v1/approvals/workflows", () => {
        posted();
        return HttpResponse.json(baseWorkflow, { status: 201 });
      }),
    );
    render(<WorkflowSettingsPage />, { wrapper: createWrapper() });
    await screen.findByText("No workflows configured");
    fireEvent.click(screen.getByRole("button", { name: "Create Workflow" }));

    expect(
      screen.getByText(
        "No switched-on module asks for approvals. Switch on the module for warehouse documents, purchase orders or equipment checkouts first.",
      ),
    ).toBeInTheDocument();
    expect(offeredTargets()).toEqual([]);
    fireEvent.change(screen.getByTestId("workflow-name-input"), {
      target: { value: "Orphan" },
    });
    await chooseEveryone();
    await openTheStage();
    const submit = screen.getByTestId(
      "workflow-submit-btn",
    ) as HTMLButtonElement;
    expect(submit.disabled).toBe(true);
    fireEvent.click(submit);
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(posted).not.toHaveBeenCalled();
  });

  it("offers every integrated target type, under a named field", async () => {
    server.use(
      http.get("/api/v1/approvals/workflows", () =>
        HttpResponse.json(onePage([])),
      ),
    );
    render(<WorkflowSettingsPage />, { wrapper: createWrapper() });
    await screen.findByText("No workflows configured");
    fireEvent.click(screen.getByRole("button", { name: "Create Workflow" }));
    // Purchase orders and equipment checkouts both request approval, so a
    // workflow for them has to be creatable here — the screen used to offer
    // documents alone, which left the "require approval" setting unusable.
    // The trigger carries the field name; the options ride the native select
    // Radix keeps in the form for submission.
    expect(
      screen.getByRole("combobox", { name: /Target type/ }),
    ).toHaveTextContent("Document");
    expect(offeredTargets()).toEqual([...AVAILABLE_TARGET_TYPES]);
  });

  it("says what a document workflow decides, and when it is the whole rule", async () => {
    server.use(
      http.get("/api/v1/approvals/workflows", () =>
        HttpResponse.json(onePage([])),
      ),
    );
    render(<WorkflowSettingsPage />, { wrapper: createWrapper() });
    await screen.findByText("No workflows configured");
    fireEvent.click(screen.getByRole("button", { name: "Create Workflow" }));

    // A workflow is the *who*: it stands in for a silent document profile,
    // while a configured threshold or type list stays the filter. The screen
    // used to say the stages were all a workflow did, and later that the
    // workflow sent every confirmed document to approval.
    expect(screen.getByTestId("workflow-gates-documents")).toHaveTextContent(
      /decides who approves/i,
    );
    expect(screen.getByTestId("workflow-gates-documents")).toHaveTextContent(
      /only while the document settings name nothing/i,
    );
  });

  it("asks before saving a stage nobody could decide, and saves it on consent", async () => {
    const bodies: Record<string, unknown>[] = [];
    server.use(
      http.get("/api/v1/approvals/workflows", () =>
        HttpResponse.json(onePage([])),
      ),
      http.post("/api/v1/approvals/workflows", async ({ request }) => {
        const body = (await request.json()) as Record<string, unknown>;
        bodies.push(body);
        // The server refuses an open stage in an organization that has
        // granted the approve right to nobody, and accepts it when the
        // request says the refusal was read and accepted.
        if (body.allow_undecidable_stages !== true) {
          return HttpResponse.json(
            {
              detail: {
                code: "APPROVAL_STAGE_UNSOLVABLE",
                message:
                  'Stage "Nobody stage" waits for anyone holding the approvals approve permission, and nobody in this organization holds it.',
              },
            },
            { status: 409 },
          );
        }
        return HttpResponse.json(
          { ...baseWorkflow, ...body, id: "wf-new" },
          { status: 201 },
        );
      }),
    );

    render(<WorkflowSettingsPage />, { wrapper: createWrapper() });
    await screen.findByText("No workflows configured");
    fireEvent.click(screen.getByRole("button", { name: "Create Workflow" }));
    fireEvent.change(screen.getByTestId("workflow-name-input"), {
      target: { value: "Documents" },
    });
    await chooseEveryone();
    await openTheStage();
    fireEvent.click(screen.getByTestId("workflow-submit-btn"));

    const dialog = await screen.findByRole("alertdialog");
    expect(within(dialog).getByText(/Nobody stage/)).toBeInTheDocument();
    expect(bodies).toHaveLength(1);

    fireEvent.click(
      within(dialog).getByRole("button", { name: "Save anyway" }),
    );
    await waitFor(() => expect(bodies).toHaveLength(2));
    expect(bodies[1].allow_undecidable_stages).toBe(true);
  });

  it("does not say that others go through unapproved once everyone is chosen", async () => {
    // The "chosen people" hint was printed for every answer, so choosing
    // Everyone was followed by "Submissions by anyone else go through".
    server.use(
      http.get("/api/v1/approvals/workflows", () =>
        HttpResponse.json(onePage([])),
      ),
    );
    render(<WorkflowSettingsPage />, { wrapper: createWrapper() });
    await screen.findByText("No workflows configured");
    fireEvent.click(screen.getByRole("button", { name: "Create Workflow" }));

    await chooseEveryone();

    expect(
      screen.getByText("Everyone's submissions are covered by this workflow."),
    ).toBeInTheDocument();
    expect(
      screen.queryByText(/anyone else go through without approval/),
    ).not.toBeInTheDocument();
  });

  it("keeps the submit button disabled until a name and whose submissions are given", async () => {
    server.use(
      http.get("/api/v1/approvals/workflows", () =>
        HttpResponse.json(onePage([])),
      ),
    );
    render(<WorkflowSettingsPage />, { wrapper: createWrapper() });
    await screen.findByText("No workflows configured");
    fireEvent.click(screen.getByRole("button", { name: "Create Workflow" }));
    const submit = screen.getByTestId(
      "workflow-submit-btn",
    ) as HTMLButtonElement;
    expect(submit.disabled).toBe(true);
    fireEvent.change(screen.getByTestId("workflow-name-input"), {
      target: { value: "Some Name" },
    });
    // A name is not enough: whose submissions it holds has no default.
    expect(submit.disabled).toBe(true);
    await chooseEveryone();
    // Nor is that: the first stage names people, and nobody is named yet.
    expect(submit.disabled).toBe(true);
    expect(
      screen.getByText(
        "Name at least one person, or let anyone with the approve permission decide.",
      ),
    ).toBeInTheDocument();
    await openTheStage();
    expect(submit.disabled).toBe(false);
  });

  it("sends each stage as its name and its people, nothing the form keeps for itself", async () => {
    let body: Record<string, unknown> | null = null;
    server.use(
      http.get("/api/v1/approvals/workflows", () =>
        HttpResponse.json(onePage([])),
      ),
      http.post("/api/v1/approvals/workflows", async ({ request }) => {
        body = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json(
          { ...baseWorkflow, ...body, id: "wf-new" },
          { status: 201 },
        );
      }),
    );
    render(<WorkflowSettingsPage />, { wrapper: createWrapper() });
    await screen.findByText("No workflows configured");
    fireEvent.click(screen.getByRole("button", { name: "Create Workflow" }));
    fireEvent.change(screen.getByTestId("workflow-name-input"), {
      target: { value: "Documents" },
    });
    await chooseEveryone();
    await openTheStage();
    fireEvent.click(screen.getByTestId("workflow-submit-btn"));

    await waitFor(() => expect(body).not.toBeNull());
    expect(body!.stages).toEqual([
      { order: 1, label: "Manager approval", approver_user_ids: [] },
    ]);
  });

  it("POSTs to /workflows with the form data on save", async () => {
    server.use(
      http.get("/api/v1/approvals/workflows", () =>
        HttpResponse.json(onePage([])),
      ),
      http.post("/api/v1/approvals/workflows", async ({ request }) => {
        const body = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json(
          { ...baseWorkflow, ...body, id: "wf-new" },
          { status: 201 },
        );
      }),
    );
    render(<WorkflowSettingsPage />, { wrapper: createWrapper() });
    await screen.findByText("No workflows configured");
    fireEvent.click(screen.getByRole("button", { name: "Create Workflow" }));
    fireEvent.change(screen.getByTestId("workflow-name-input"), {
      target: { value: "My Workflow" },
    });
    await chooseEveryone();
    await openTheStage();
    fireEvent.click(screen.getByTestId("workflow-submit-btn"));
    await waitFor(() => {
      expect(
        screen.queryByTestId("workflow-name-input"),
      ).not.toBeInTheDocument();
    });
  });

  it("shows an error toast when create fails", async () => {
    server.use(
      http.get("/api/v1/approvals/workflows", () =>
        HttpResponse.json(onePage([])),
      ),
      http.post("/api/v1/approvals/workflows", () =>
        HttpResponse.json(
          {
            detail: "Cannot modify workflow: 3 active request(s) in progress.",
          },
          { status: 409 },
        ),
      ),
    );
    const { toast } = await import("sonner");
    render(<WorkflowSettingsPage />, { wrapper: createWrapper() });
    await screen.findByText("No workflows configured");
    fireEvent.click(screen.getByRole("button", { name: "Create Workflow" }));
    fireEvent.change(screen.getByTestId("workflow-name-input"), {
      target: { value: "X" },
    });
    await chooseEveryone();
    await openTheStage();
    fireEvent.click(screen.getByTestId("workflow-submit-btn"));
    // The server's refusal names the requests waiting and the move that
    // exists; the page used to swap it for a stock sentence whenever the
    // text happened to contain "active request".
    await waitFor(() => {
      expect(toast.error).toHaveBeenCalledWith(
        "Cannot modify workflow: 3 active request(s) in progress.",
      );
    });
  });

  it("shows the server's refusal when switching a workflow off is refused", async () => {
    server.use(
      http.get("/api/v1/approvals/workflows", () =>
        HttpResponse.json(onePage([baseWorkflow])),
      ),
      http.patch("/api/v1/approvals/workflows/:id", () =>
        HttpResponse.json(
          {
            detail:
              "This workflow cannot be changed while requests are waiting on it (1: IN/2026/001).",
          },
          { status: 409 },
        ),
      ),
    );
    render(<WorkflowSettingsPage />, { wrapper: createWrapper() });
    fireEvent.click(await screen.findByRole("button", { name: "Deactivate" }));
    const dialog = await screen.findByRole("alertdialog");
    await waitFor(() =>
      expect(
        within(dialog).getByRole("button", { name: "Deactivate" }),
      ).toBeEnabled(),
    );
    fireEvent.click(within(dialog).getByRole("button", { name: "Deactivate" }));
    // The rejection stays inside the dialog (the ConfirmDialog contract).
    await waitFor(() =>
      expect(screen.getByRole("alertdialog")).toHaveTextContent(
        "This workflow cannot be changed while requests are waiting on it (1: IN/2026/001).",
      ),
    );
  });

  it("starts edit mode when Edit is clicked", async () => {
    server.use(
      http.get("/api/v1/approvals/workflows", () =>
        HttpResponse.json(onePage([baseWorkflow])),
      ),
    );
    render(<WorkflowSettingsPage />, { wrapper: createWrapper() });
    const editBtn = await screen.findByText("Edit");
    fireEvent.click(editBtn);
    const input = screen.getByTestId("workflow-name-input") as HTMLInputElement;
    expect(input.value).toBe("Document Approval");
  });

  it("says why Save Changes is off when the name is cleared", async () => {
    // The button went dead with nothing on screen saying the name is required.
    server.use(
      http.get("/api/v1/approvals/workflows", () =>
        HttpResponse.json(onePage([baseWorkflow])),
      ),
    );
    render(<WorkflowSettingsPage />, { wrapper: createWrapper() });
    fireEvent.click(await screen.findByText("Edit"));
    const submit = screen.getByTestId(
      "workflow-submit-btn",
    ) as HTMLButtonElement;
    expect(submit.disabled).toBe(false);
    expect(screen.queryByText("Please enter a workflow name")).toBeNull();

    fireEvent.change(screen.getByTestId("workflow-name-input"), {
      target: { value: "" },
    });

    expect(submit.disabled).toBe(true);
    expect(
      screen.getByText("Please enter a workflow name"),
    ).toBeInTheDocument();
  });

  it("PATCHes the workflow when saving in edit mode", async () => {
    let receivedBody: Record<string, unknown> | null = null;
    server.use(
      http.get("/api/v1/approvals/workflows", () =>
        HttpResponse.json(onePage([baseWorkflow])),
      ),
      http.patch("/api/v1/approvals/workflows/:id", async ({ request }) => {
        receivedBody = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json({ ...baseWorkflow, ...receivedBody });
      }),
    );
    render(<WorkflowSettingsPage />, { wrapper: createWrapper() });
    const editBtn = await screen.findByText("Edit");
    fireEvent.click(editBtn);
    fireEvent.change(screen.getByTestId("workflow-name-input"), {
      target: { value: "Renamed" },
    });
    fireEvent.click(screen.getByTestId("workflow-submit-btn"));
    await waitFor(() => {
      expect(receivedBody).not.toBeNull();
    });
    expect(
      (receivedBody as unknown as Record<string, unknown> | undefined)?.name,
    ).toBe("Renamed");
  });

  it("DELETEs the workflow after the user confirms", async () => {
    let deletedId = "";
    server.use(
      http.get("/api/v1/approvals/workflows", () =>
        HttpResponse.json(onePage([baseWorkflow])),
      ),
      http.delete("/api/v1/approvals/workflows/:id", ({ params }) => {
        deletedId = params.id as string;
        return new HttpResponse(null, { status: 204 });
      }),
    );
    render(<WorkflowSettingsPage />, { wrapper: createWrapper() });
    // Multiple Delete buttons exist (card + dialog). The first one is in the card.
    const deleteButtons = await screen.findAllByRole("button", {
      name: "Delete",
    });
    fireEvent.click(deleteButtons[0]);
    const dialog = await screen.findByRole("alertdialog");
    const confirmBtn = within(dialog).getByRole("button", { name: "Delete" });
    // The dialog counts what waits before it lets the answer through.
    await waitFor(() => expect(confirmBtn).toBeEnabled());
    fireEvent.click(confirmBtn);
    await waitFor(() => {
      expect(deletedId).toBe("wf-1");
    });
  });

  describe("deleting while the editor is open", () => {
    const otherWorkflow = {
      ...baseWorkflow,
      id: "wf-2",
      target_type: "stock_adjustment",
      name: "Stock Approval",
    };

    /** Lists both workflows until the first delete, then the one left. */
    const serveTwoWorkflows = () => {
      let remaining = [baseWorkflow, otherWorkflow];
      server.use(
        http.get("/api/v1/approvals/workflows", () =>
          HttpResponse.json(onePage(remaining)),
        ),
        http.delete("/api/v1/approvals/workflows/:id", ({ params }) => {
          remaining = remaining.filter((w) => w.id !== params.id);
          return new HttpResponse(null, { status: 204 });
        }),
      );
    };

    const deleteCard = async (index: number) => {
      fireEvent.click(
        (await screen.findAllByRole("button", { name: "Delete" }))[index],
      );
      const dialog = await screen.findByRole("alertdialog");
      const confirmBtn = within(dialog).getByRole("button", { name: "Delete" });
      await waitFor(() => expect(confirmBtn).toBeEnabled());
      fireEvent.click(confirmBtn);
    };

    it("closes the editor of the workflow that was deleted", async () => {
      serveTwoWorkflows();
      render(<WorkflowSettingsPage />, { wrapper: createWrapper() });
      fireEvent.click((await screen.findAllByText("Edit"))[0]);
      expect(
        (screen.getByTestId("workflow-name-input") as HTMLInputElement).value,
      ).toBe("Document Approval");

      await deleteCard(0);

      await waitFor(() =>
        expect(screen.queryByTestId("workflow-name-input")).toBeNull(),
      );
    });

    it("keeps the editor and its draft when another workflow is deleted", async () => {
      serveTwoWorkflows();
      render(<WorkflowSettingsPage />, { wrapper: createWrapper() });
      fireEvent.click((await screen.findAllByText("Edit"))[0]);
      fireEvent.change(screen.getByTestId("workflow-name-input"), {
        target: { value: "Half-typed rename" },
      });

      await deleteCard(1);

      await waitFor(() =>
        expect(screen.queryByText("Stock Approval")).toBeNull(),
      );
      expect(
        (screen.getByTestId("workflow-name-input") as HTMLInputElement).value,
      ).toBe("Half-typed rename");
    });
  });

  it("says where an archived workflow's requests went, and opens them", async () => {
    server.use(
      http.get("/api/v1/approvals/workflows", () =>
        HttpResponse.json(onePage([baseWorkflow])),
      ),
      http.delete("/api/v1/approvals/workflows/:id", () =>
        HttpResponse.json({ archived: true, requests_kept: 2 }),
      ),
    );
    const { toast } = await import("sonner");
    function Where() {
      const location = useLocation();
      return (
        <span data-testid="where">{location.pathname + location.search}</span>
      );
    }
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: { retry: false },
        mutations: { retry: false },
      },
    });
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={["/approvals/workflows"]}>
          <Where />
          <WorkflowSettingsPage />
        </MemoryRouter>
      </QueryClientProvider>,
    );
    fireEvent.click(
      (await screen.findAllByRole("button", { name: "Delete" }))[0],
    );
    const dialog = await screen.findByRole("alertdialog");
    const confirmBtn = within(dialog).getByRole("button", { name: "Delete" });
    await waitFor(() => expect(confirmBtn).toBeEnabled());
    fireEvent.click(confirmBtn);

    await waitFor(() => expect(toast.success).toHaveBeenCalled());
    const [message, options] = vi.mocked(toast.success).mock.calls[0] as [
      string,
      { action: { label: string; onClick: () => void } },
    ];
    expect(message).toBe(
      "Workflow deleted. Its 2 approval requests stay on the Approvals dashboard, under All.",
    );
    expect(options.action.label).toBe("Show requests");
    act(() => options.action.onClick());
    // The dashboard opens on what is open; these requests are all closed.
    expect(screen.getByTestId("where")).toHaveTextContent(
      /^\/approvals\?status=$/,
    );
  });

  it("shows an error toast when delete fails", async () => {
    server.use(
      http.get("/api/v1/approvals/workflows", () =>
        HttpResponse.json(onePage([baseWorkflow])),
      ),
      http.delete("/api/v1/approvals/workflows/:id", () =>
        HttpResponse.json(
          {
            detail: "Cannot delete workflow: 2 active request(s) in progress.",
          },
          { status: 409 },
        ),
      ),
    );
    const { toast } = await import("sonner");
    render(<WorkflowSettingsPage />, { wrapper: createWrapper() });
    const deleteButtons = await screen.findAllByRole("button", {
      name: "Delete",
    });
    fireEvent.click(deleteButtons[0]);
    const dialog = await screen.findByRole("alertdialog");
    const confirmBtn = within(dialog).getByRole("button", { name: "Delete" });
    // The dialog counts what waits before it lets the answer through.
    await waitFor(() => expect(confirmBtn).toBeEnabled());
    fireEvent.click(confirmBtn);
    // The 409 carries the reason ("2 active request(s) in progress") — it is
    // shown inside the dialog, which stays open, instead of a generic sentence.
    await waitFor(() => {
      expect(dialog).toHaveTextContent(
        "Cannot delete workflow: 2 active request(s) in progress.",
      );
    });
    expect(toast.error).not.toHaveBeenCalled();
  });
});

describe("WorkflowSettingsPage without approvals:configure", () => {
  // Listing workflows needs no grant, so the page stays readable — only the
  // mutations the API would refuse are taken away.
  beforeEach(() => {
    signInWith(["approvals:read"]);
  });

  it("keeps the configured workflows visible", async () => {
    server.use(
      http.get("/api/v1/approvals/workflows", () =>
        HttpResponse.json(onePage([baseWorkflow])),
      ),
    );

    render(<WorkflowSettingsPage />, { wrapper: createWrapper() });

    expect(await screen.findByText("Document Approval")).toBeInTheDocument();
  });

  it("offers no Edit or Delete on them", async () => {
    server.use(
      http.get("/api/v1/approvals/workflows", () =>
        HttpResponse.json(onePage([baseWorkflow])),
      ),
    );

    render(<WorkflowSettingsPage />, { wrapper: createWrapper() });
    await screen.findByText("Document Approval");

    expect(
      screen.queryByRole("button", { name: "Edit" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Delete" }),
    ).not.toBeInTheDocument();
  });

  it("puts no Create button in the page header", async () => {
    server.use(
      http.get("/api/v1/approvals/workflows", () =>
        HttpResponse.json(onePage([baseWorkflow])),
      ),
    );

    render(<WorkflowSettingsPage />, { wrapper: createWrapper() });
    await screen.findByText("Document Approval");

    expect(setHeader).toHaveBeenCalled();
    for (const [header] of setHeader.mock.calls) {
      expect(header.actions).toBeUndefined();
    }
  });

  it("drops the create invitation from the empty state", async () => {
    server.use(
      http.get("/api/v1/approvals/workflows", () =>
        HttpResponse.json(onePage([])),
      ),
    );

    render(<WorkflowSettingsPage />, { wrapper: createWrapper() });
    await screen.findByText("No workflows configured");

    expect(
      screen.queryByRole("button", { name: "Create Workflow" }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByText(
        "No workflow has been configured yet. Ask someone who can configure workflows to add one.",
      ),
    ).toBeInTheDocument();
  });
});

/**
 * The approval path form is a page form: name, target type and a stage list,
 * typed by hand, with the module tabs one click away. The equipment and
 * product forms ask before a tab takes the page; this one used to let the
 * draft go in silence.
 */
function GuardedShell({ children }: { children: React.ReactNode }) {
  const { guardClick, confirmDialogProps } = useNavLeaveGuard();
  const location = useLocation();
  return (
    <div onClickCapture={guardClick}>
      <Link to="/approvals">Approvals list</Link>
      <span data-testid="path">{location.pathname}</span>
      {children}
      <ConfirmDialog {...confirmDialogProps} />
    </div>
  );
}

function renderInShell() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={["/approvals/workflows"]}>
        <GuardedShell>
          <WorkflowSettingsPage />
        </GuardedShell>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("WorkflowSettingsPage — the nav-leave guard", () => {
  beforeEach(() => {
    useFormGuardStore.getState().setDirtyForm(null);
    server.use(
      http.get("/api/v1/approvals/workflows", () =>
        HttpResponse.json(onePage([])),
      ),
    );
  });

  it("stays quiet for an untouched form and names itself once something is typed", async () => {
    render(<WorkflowSettingsPage />, { wrapper: createWrapper() });
    await screen.findByText("No workflows configured");

    fireEvent.click(screen.getByRole("button", { name: "Create Workflow" }));
    // An open form nobody has touched is not the reader's work. Asking
    // about it would teach the reader to click through the question.
    expect(screen.getByTestId("workflow-name-input")).toBeInTheDocument();
    expect(useFormGuardStore.getState().dirtyForm).toBeNull();

    fireEvent.change(screen.getByTestId("workflow-name-input"), {
      target: { value: "Documents" },
    });
    await waitFor(() =>
      expect(useFormGuardStore.getState().dirtyForm).toBe(
        "The approval path form",
      ),
    );
  });

  it("drops the claim when the form closes", async () => {
    render(<WorkflowSettingsPage />, { wrapper: createWrapper() });
    await screen.findByText("No workflows configured");

    fireEvent.click(screen.getByRole("button", { name: "Create Workflow" }));
    fireEvent.change(screen.getByTestId("workflow-name-input"), {
      target: { value: "Documents" },
    });
    await waitFor(() =>
      expect(useFormGuardStore.getState().dirtyForm).not.toBeNull(),
    );

    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    await waitFor(() =>
      expect(useFormGuardStore.getState().dirtyForm).toBeNull(),
    );
  });

  it("holds a module link until the reader says to leave", async () => {
    const user = userEvent.setup();
    renderInShell();
    await screen.findByText("No workflows configured");

    await user.click(screen.getByRole("button", { name: "Create Workflow" }));
    fireEvent.change(screen.getByTestId("workflow-name-input"), {
      target: { value: "Documents" },
    });
    await waitFor(() =>
      expect(useFormGuardStore.getState().dirtyForm).not.toBeNull(),
    );

    await user.click(screen.getByText("Approvals list"));

    expect(screen.getByTestId("path")).toHaveTextContent(
      "/approvals/workflows",
    );
    expect(screen.getByText("Unsaved changes")).toBeInTheDocument();
    expect(
      screen.getByText(
        "The approval path form holds unsaved changes. Leave anyway?",
      ),
    ).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Leave anyway" }));
    await waitFor(() =>
      expect(screen.getByTestId("path")).toHaveTextContent("/approvals"),
    );
  });
});

describe("WorkflowSettingsPage — whose submissions a workflow holds", () => {
  const rolesHandler = http.get("/api/v1/roles", () =>
    HttpResponse.json(
      onePage([
        {
          id: "r-user",
          organization_id: null,
          name: "user",
          permissions: [],
          is_system: true,
          created_at: null,
          member_count: 3,
        },
        {
          id: "r-store",
          organization_id: "org-1",
          name: "Storeman",
          permissions: [],
          is_system: false,
          created_at: null,
          member_count: 2,
        },
      ]),
    ),
  );

  const scoped = {
    ...baseWorkflow,
    requester_scope: {
      everyone: false,
      user_ids: ["u-k"],
      role_ids: ["r-store"],
    },
    requesters: [
      { kind: "role", id: "r-store", name: "Storeman", is_system: false },
      { kind: "user", id: "u-k", name: "Kasia", is_system: false },
    ],
  };

  it("names on the card whose documents each workflow holds", async () => {
    server.use(
      http.get("/api/v1/approvals/workflows", () =>
        HttpResponse.json(onePage([scoped, { ...baseWorkflow, id: "wf-2" }])),
      ),
    );
    render(<WorkflowSettingsPage />, { wrapper: createWrapper() });

    expect(
      await screen.findByTestId("workflow-requesters-wf-1"),
    ).toHaveTextContent("Documents submitted by: Storeman, Kasia");
    expect(screen.getByTestId("workflow-requesters-wf-2")).toHaveTextContent(
      "Documents submitted by: everyone",
    );
  });

  it("says it again in the switch-on dialog", async () => {
    server.use(
      http.get("/api/v1/approvals/workflows", () =>
        HttpResponse.json(onePage([{ ...scoped, is_active: false }])),
      ),
    );
    render(<WorkflowSettingsPage />, { wrapper: createWrapper() });
    await screen.findByTestId("workflow-requesters-wf-1");

    fireEvent.click(screen.getByRole("button", { name: "Activate" }));

    const dialog = await screen.findByRole("alertdialog");
    expect(
      within(dialog).getByText("Documents submitted by: Storeman, Kasia"),
    ).toBeInTheDocument();
  });

  it("saves the roles chosen, and not before somebody is chosen", async () => {
    let body: Record<string, unknown> | null = null;
    server.use(
      rolesHandler,
      http.get("/api/v1/approvals/workflows", () =>
        HttpResponse.json(onePage([])),
      ),
      http.post("/api/v1/approvals/workflows", async ({ request }) => {
        body = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json(
          { ...baseWorkflow, ...body, id: "wf-new" },
          { status: 201 },
        );
      }),
    );
    render(<WorkflowSettingsPage />, { wrapper: createWrapper() });
    await screen.findByText("No workflows configured");
    fireEvent.click(screen.getByRole("button", { name: "Create Workflow" }));
    fireEvent.change(screen.getByTestId("workflow-name-input"), {
      target: { value: "Receipts by the warehouse" },
    });
    await userEvent.click(
      screen.getByRole("combobox", { name: /Who it applies to/ }),
    );
    await userEvent.click(
      await screen.findByRole("option", { name: "Chosen people and roles" }),
    );
    await openTheStage();

    const submit = screen.getByTestId("workflow-submit-btn");
    expect(
      screen.getByText("Choose at least one person or role."),
    ).toBeInTheDocument();
    expect(submit).toBeDisabled();

    fireEvent.click(await screen.findByRole("checkbox", { name: "Storeman" }));
    expect(submit).toBeEnabled();
    fireEvent.click(submit);

    await waitFor(() => expect(body).not.toBeNull());
    expect(body!.requester_scope).toEqual({
      everyone: false,
      user_ids: [],
      role_ids: ["r-store"],
    });
  });

  it("offers people alone when the roles list is closed to the reader", async () => {
    server.use(
      http.get("/api/v1/roles", () =>
        HttpResponse.json({ detail: "Forbidden" }, { status: 403 }),
      ),
      http.get("/api/v1/approvals/workflows", () =>
        HttpResponse.json(onePage([])),
      ),
    );
    render(<WorkflowSettingsPage />, { wrapper: createWrapper() });
    await screen.findByText("No workflows configured");
    fireEvent.click(screen.getByRole("button", { name: "Create Workflow" }));
    await userEvent.click(
      screen.getByRole("combobox", { name: /Who it applies to/ }),
    );
    await userEvent.click(
      await screen.findByRole("option", { name: "Chosen people and roles" }),
    );

    expect(
      await screen.findByText(
        "The list of roles is not available to you; choose people instead.",
      ),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /Add person/ }),
    ).toBeInTheDocument();
  });
});
