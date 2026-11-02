/**
 * The notice over a request nobody can decide tells the reader what they can
 * do, and the three readers can do different things: the requester can
 * withdraw, an administrator can give the access, everybody else can only ask.
 * It never advises the one move that looks obvious and is refused — changing
 * the workflow while the request waits on it.
 */
import { beforeEach, describe, expect, it } from "vitest";
import { render, screen, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { http, HttpResponse } from "msw";

import { server } from "@/test/mocks/server";
import { signInWith } from "@/test/auth";
import { ApprovalDeadEndNotice } from "../components/ApprovalDeadEndNotice";
import { onePage } from "@/test/mocks/page";

const REQUESTER = "user-requester";
const NAMED = "user-blind";

const request = {
  created_by: REQUESTER,
  created_by_name: "Rita Requester",
  current_stage: 1,
  workflow_stages: [
    {
      order: 1,
      role: "manager",
      label: "Peer review",
      approver_user_ids: [NAMED],
    },
  ],
};

function renderNotice(
  props: Partial<React.ComponentProps<typeof ApprovalDeadEndNotice>>,
) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <ApprovalDeadEndNotice
          subject={{
            solvable: false,
            undecidable_reason: "named_approvers_cannot_decide",
          }}
          request={request}
          {...props}
        />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  server.use(
    http.get("/api/v1/users/org-members", () =>
      HttpResponse.json(
        onePage([
          { id: NAMED, full_name: "Bob Blind", email: "bob@example.com" },
          {
            id: REQUESTER,
            full_name: "Rita Requester",
            email: "rita@example.com",
          },
        ]),
      ),
    ),
  );
});

describe("ApprovalDeadEndNotice — when the members cannot be read", () => {
  it("says so instead of naming nobody", async () => {
    server.use(
      http.get(
        "/api/v1/users/org-members",
        () => new HttpResponse(null, { status: 500 }),
      ),
    );
    signInWith([], { id: REQUESTER });
    renderNotice({});

    const note = await screen.findByRole("note");
    expect(await within(note).findByRole("alert")).toBeInTheDocument();
    expect(
      within(note).getByRole("button", { name: /try again/i }),
    ).toBeInTheDocument();
  });
});

describe("ApprovalDeadEndNotice — what each reader can do", () => {
  it("tells the requester to withdraw, and what happens to the document", async () => {
    signInWith([], { id: REQUESTER });
    renderNotice({});

    const note = await screen.findByRole("note");
    expect(within(note).getByText(/Withdraw the request/)).toBeInTheDocument();
    // What follows the withdrawal is said before the click, not discovered.
    expect(
      within(note).getByText(/goes back to Confirmed/),
    ).toBeInTheDocument();
    // Nothing for the requester to chase through a screen they cannot use.
    expect(within(note).queryByRole("link")).not.toBeInTheDocument();
    expect(within(note).getByText(/Ask an administrator/)).toBeInTheDocument();
  });

  it("gives an administrator the named person and the screen to give access", async () => {
    signInWith(["admin:access"], { id: "admin-1" });
    renderNotice({});

    const note = await screen.findByRole("note");
    expect(
      await within(note).findByText(/Give Bob Blind access to approvals/),
    ).toBeInTheDocument();
    expect(
      within(note).getByRole("link", { name: "Members and roles" }),
    ).toHaveAttribute("href", "/settings");
    // The administrator is not the requester: withdrawing is not theirs.
    expect(within(note).queryByText(/Withdraw the request/)).toBeNull();
    expect(
      within(note).getByText(/Ask Rita Requester to withdraw the request/),
    ).toBeInTheDocument();
  });

  it("never advises changing or switching off the workflow", async () => {
    signInWith(["admin:access"], { id: "admin-1" });
    renderNotice({});

    const note = await screen.findByRole("note");
    // The refusal the server gives is said as a fact, not offered as a move.
    expect(
      within(note).getByText(/cannot be changed or switched off/),
    ).toBeInTheDocument();
    expect(note.textContent).not.toMatch(/change the stage/i);
    expect(note.textContent).not.toMatch(/edit the stage/i);
  });

  it("an administrator who is also the requester gets both ways out", async () => {
    signInWith(["admin:access"], { id: REQUESTER });
    renderNotice({});

    const note = await screen.findByRole("note");
    expect(within(note).getByText(/Withdraw the request/)).toBeInTheDocument();
    expect(
      within(note).getByRole("link", { name: "Members and roles" }),
    ).toBeInTheDocument();
    expect(within(note).queryByText(/Ask Rita Requester/)).toBeNull();
  });

  it("tells anybody else whom to ask", async () => {
    signInWith(["approvals:read"], { id: "bystander" });
    renderNotice({});

    const note = await screen.findByRole("note");
    expect(
      await within(note).findByText(
        /Ask an administrator to give Bob Blind access to approvals/,
      ),
    ).toBeInTheDocument();
    expect(
      within(note).getByText(/Ask Rita Requester to withdraw the request/),
    ).toBeInTheDocument();
    expect(within(note).queryByRole("link")).not.toBeInTheDocument();
    expect(within(note).queryByText(/Withdraw the request\./)).toBeNull();
  });

  it("points an administrator at the role screen when nobody holds the grant", async () => {
    signInWith(["admin:access"], { id: "admin-1" });
    renderNotice({
      subject: {
        solvable: false,
        undecidable_reason: "no_approver_in_organization",
      },
    });

    const note = await screen.findByRole("note");
    expect(within(note).getByRole("link", { name: "Roles" })).toHaveAttribute(
      "href",
      "/settings/roles",
    );
  });

  it("offers the self-approval switch when the only holder is the requester", async () => {
    signInWith(["admin:access"], { id: "admin-1" });
    renderNotice({
      subject: {
        solvable: false,
        undecidable_reason: "only_the_requester_can_decide",
      },
    });

    const note = await screen.findByRole("note");
    expect(
      within(note).getByRole("link", { name: "Approval settings" }),
    ).toHaveAttribute("href", "/settings/modules/approvals");
  });

  it("says nothing when somebody can decide", () => {
    signInWith([], { id: REQUESTER });
    renderNotice({ subject: { solvable: true } });

    expect(screen.queryByRole("note")).not.toBeInTheDocument();
  });
});

describe("ApprovalDeadEndNotice — on a workflow", () => {
  it("names the requests already parked there, each a link to its record", async () => {
    signInWith(["admin:access"], { id: "admin-1" });
    renderNotice({
      request: undefined,
      waiting: [
        {
          request_id: "r1",
          target_type: "document",
          target_id: "d1",
          label: "IN/2026/001",
        },
        {
          request_id: "r2",
          target_type: "document",
          target_id: "d2",
          label: "IN/2026/002",
        },
      ],
    });

    const note = await screen.findByRole("note");
    expect(within(note).getByText(/Already waiting here/)).toBeInTheDocument();
    expect(
      within(note).getByRole("link", { name: "IN/2026/001" }),
    ).toHaveAttribute("href", "/warehouse/documents/d1");
    expect(
      within(note).getByRole("link", { name: "IN/2026/002" }),
    ).toHaveAttribute("href", "/warehouse/documents/d2");
    // Editing the stage is not on offer while they wait.
    expect(note.textContent).not.toMatch(/or edit the stage/i);
    expect(note.textContent).toMatch(/cannot be changed while they wait/);
  });

  it("offers the edit only while nothing waits", async () => {
    signInWith(["admin:access"], { id: "admin-1" });
    renderNotice({ request: undefined, waiting: [] });

    const note = await screen.findByRole("note");
    expect(note.textContent).toMatch(/or edit the stage/i);
    expect(within(note).queryByText(/Already waiting here/)).toBeNull();
  });
});
