import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter } from "react-router-dom";
import { http, HttpResponse } from "msw";

import WorkflowSettingsPage from "../pages/WorkflowSettingsPage";
import { server } from "@/test/mocks/server";
import { signInWith } from "@/test/auth";
import * as modulesCtx from "@/contexts/ModulesContext";
import { onePage } from "@/test/mocks/page";

/*
 * A workflow comes into force only when somebody switches it on, knowing what
 * it will hold. It used to hold every confirmed document the moment it was
 * saved under a silent document profile, with nothing on the screen saying so.
 */

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn(), warning: vi.fn() },
}));

vi.mock("@/hooks/useModulePageHeader", () => ({
  useModulePageHeader: () => ({ setHeader: vi.fn() }),
}));

const everyDocument = {
  holds: "all" as const,
  conditions: [],
  required_by_settings: [],
};

const onlyIssues = {
  holds: "some" as const,
  conditions: [
    {
      kind: "document_types" as const,
      document_types: ["OUT"],
      amount: null,
      currency: null,
      unpriced_included: false,
    },
  ],
  required_by_settings: ["approval_required_for_types"],
};

const workflow = {
  id: "wf-1",
  organization_id: "org-1",
  target_type: "document",
  name: "Receipts sign-off",
  stages: [
    {
      order: 1,
      role: "manager",
      label: "Manager Review",
      approver_user_ids: [],
    },
  ],
  is_active: false,
  requester_scope: { everyone: true, user_ids: [], role_ids: [] },
  created_at: new Date().toISOString(),
  updated_at: null,
  solvable: true,
  undecidable_reason: null,
  scope: everyDocument,
};

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <WorkflowSettingsPage />
      </BrowserRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.spyOn(modulesCtx, "useModules").mockReturnValue({
    enabledModules: ["approvals"],
    isModuleEnabled: (name: string) => name === "approvals",
    isLoading: false,
    refreshModules: vi.fn(),
    focusModule: null,
    hiddenModules: [],
  });
  vi.clearAllMocks();
  server.resetHandlers();
  server.use(
    http.get("/api/v1/users/org-members", () => HttpResponse.json(onePage([]))),
  );
  signInWith(["approvals:configure"]);
});

describe("Switching a workflow on", () => {
  it("says on the card what a workflow that is on holds", async () => {
    server.use(
      http.get("/api/v1/approvals/workflows", () =>
        HttpResponse.json(onePage([{ ...workflow, is_active: true }])),
      ),
    );
    renderPage();
    expect(
      await screen.findByText("Holds: every confirmed document"),
    ).toBeInTheDocument();
  });

  it("says a workflow that is off holds nothing yet, and what it would", async () => {
    server.use(
      http.get("/api/v1/approvals/workflows", () =>
        HttpResponse.json(onePage([workflow])),
      ),
    );
    renderPage();
    expect(
      await screen.findByText(
        "Off — holds nothing. Once switched on: every confirmed document",
      ),
    ).toBeInTheDocument();
  });

  it("asks first, naming the scope and the settings that change it, and switches on only on yes", async () => {
    const user = userEvent.setup();
    const patches: Record<string, unknown>[] = [];
    server.use(
      http.get("/api/v1/approvals/workflows", () =>
        HttpResponse.json(onePage([{ ...workflow, scope: onlyIssues }])),
      ),
      http.patch("/api/v1/approvals/workflows/:id", async ({ request }) => {
        const body = (await request.json()) as Record<string, unknown>;
        patches.push(body);
        return HttpResponse.json({ ...workflow, ...body });
      }),
    );
    renderPage();

    await user.click(await screen.findByRole("button", { name: "Activate" }));

    const dialog = await screen.findByRole("alertdialog");
    expect(
      within(dialog).getByText(
        "From now on, these will wait for approval: documents of type Goods Issue.",
      ),
    ).toBeInTheDocument();
    expect(
      within(dialog).getByRole("link", { name: "Change what needs approval" }),
    ).toHaveAttribute("href", "/warehouse/settings?section=approvals");
    // Opening the question changed nothing yet.
    expect(patches).toEqual([]);

    await user.click(within(dialog).getByRole("button", { name: "Switch on" }));
    // The consent travels with the switch: the server refuses if the rule
    // it describes is no longer the live one.
    await waitFor(() =>
      expect(patches).toEqual([
        { is_active: true, expected_scope: onlyIssues },
      ]),
    );
  });

  it("shows the scope as it is when the dialog opens, not as the card was drawn", async () => {
    const user = userEvent.setup();
    let reads = 0;
    server.use(
      http.get("/api/v1/approvals/workflows", () => {
        reads += 1;
        // The card is drawn under a type list; by the time the reader opens
        // the dialog the settings have been cleared elsewhere.
        return HttpResponse.json(
          onePage([
            { ...workflow, scope: reads === 1 ? onlyIssues : everyDocument },
          ]),
        );
      }),
    );
    renderPage();
    expect(
      await screen.findByText(
        "Off — holds nothing. Once switched on: documents of type Goods Issue",
      ),
    ).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Activate" }));
    const dialog = await screen.findByRole("alertdialog");
    expect(
      await within(dialog).findByText(
        "From now on, these will wait for approval: every confirmed document.",
      ),
    ).toBeInTheDocument();
  });

  it("when the settings moved after it opened, says so and shows the new rule before asking again", async () => {
    const user = userEvent.setup();
    let moved = false;
    const patches: unknown[] = [];
    server.use(
      http.get("/api/v1/approvals/workflows", () =>
        HttpResponse.json(
          onePage([{ ...workflow, scope: moved ? everyDocument : onlyIssues }]),
        ),
      ),
      http.patch("/api/v1/approvals/workflows/:id", async ({ request }) => {
        patches.push(await request.json());
        moved = true;
        return HttpResponse.json(
          {
            detail: {
              code: "APPROVAL_SCOPE_CHANGED",
              message:
                "What this workflow would hold has changed since you opened this.",
            },
          },
          { status: 409 },
        );
      }),
    );
    renderPage();

    await user.click(await screen.findByRole("button", { name: "Activate" }));
    const dialog = await screen.findByRole("alertdialog");
    await within(dialog).findByText(
      "From now on, these will wait for approval: documents of type Goods Issue.",
    );
    await user.click(within(dialog).getByRole("button", { name: "Switch on" }));

    // Still open, with the server's reason and the rule that holds now.
    expect(
      await within(dialog).findByText(
        "What this workflow would hold has changed since you opened this.",
      ),
    ).toBeInTheDocument();
    expect(
      await within(dialog).findByText(
        "From now on, these will wait for approval: every confirmed document.",
      ),
    ).toBeInTheDocument();
    expect(patches).toHaveLength(1);
  });

  it("cancelling the question leaves the workflow off", async () => {
    const user = userEvent.setup();
    const patches: unknown[] = [];
    server.use(
      http.get("/api/v1/approvals/workflows", () =>
        HttpResponse.json(onePage([workflow])),
      ),
      http.patch("/api/v1/approvals/workflows/:id", async ({ request }) => {
        patches.push(await request.json());
        return HttpResponse.json(workflow);
      }),
    );
    renderPage();

    await user.click(await screen.findByRole("button", { name: "Activate" }));
    const dialog = await screen.findByRole("alertdialog");
    await user.click(within(dialog).getByRole("button", { name: /cancel/i }));

    await waitFor(() =>
      expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument(),
    );
    expect(patches).toEqual([]);
  });

  it("tells the author of a new workflow that it is saved switched off", async () => {
    const user = userEvent.setup();
    server.use(
      http.get("/api/v1/approvals/workflows", () =>
        HttpResponse.json(onePage([])),
      ),
    );
    renderPage();
    await user.click(
      await screen.findByRole("button", { name: "Create Workflow" }),
    );
    expect(
      await screen.findByText(
        "A new workflow is saved switched off — it holds nothing until you switch it on from the list.",
      ),
    ).toBeInTheDocument();
  });
});
