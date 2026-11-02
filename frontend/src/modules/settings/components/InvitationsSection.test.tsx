import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { http, HttpResponse } from "msw";
import { toast } from "sonner";
import { describe, expect, it, vi, beforeEach } from "vitest";
import InvitationsSection from "./InvitationsSection";
import { server } from "@/test/mocks/server";
import { onePage } from "@/test/mocks/page";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn(), loading: vi.fn() },
}));

function renderSection() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <InvitationsSection />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

const dayFromNow = new Date(Date.now() + 86_400_000).toISOString();
const hourAgo = new Date(Date.now() - 3_600_000).toISOString();

const ORG = {
  id: "org-1",
  name: "Test Org",
  currency: "PLN",
  settings: {} as Record<string, unknown>,
};

function withOrgSmtp(configured: boolean) {
  server.use(
    http.get("*/organizations/my", () =>
      HttpResponse.json({ ...ORG, can_send_email: configured }),
    ),
  );
}

/** One invitation nobody has redeemed yet — the row both resend cases act on. */
const PENDING_INVITATION = {
  id: "i1",
  code: "LIVE5678",
  role: "user",
  role_id: null,
  is_used: false,
  expires_at: dayFromNow,
  created_at: hourAgo,
  invited_email: "anna@example.com",
  used_by_user_id: null,
  used_at: null,
};

describe("InvitationsSection", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    server.use(
      http.get("*/organizations/my/invitations", () =>
        HttpResponse.json(onePage([])),
      ),
      http.get("*/roles", () => HttpResponse.json(onePage([]))),
    );
    withOrgSmtp(false);
  });

  it("says the roles could not be loaded instead of offering only the built-in ones", async () => {
    server.use(
      http.get("*/roles", () => new HttpResponse(null, { status: 500 })),
    );
    renderSection();

    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /try again/i }),
    ).toBeInTheDocument();
  });

  it("points at the page that actually configures mail", async () => {
    // The link read /settings?tab=email long after the settings screens moved
    // to paths — no page reads a ?tab parameter, so the offer to fix the
    // missing mail server landed on General.
    renderSection();

    expect(
      await screen.findByRole("link", { name: "Set up email" }),
    ).toHaveAttribute("href", "/settings/email");
  });

  it("refuses to issue an invitation with no recipient", async () => {
    // The whole point of the change: an invitation is a promise made to
    // somebody, and the form must not let one be made to nobody.
    let called = false;
    server.use(
      http.post("*/organizations/my/invitation-code", () => {
        called = true;
        return HttpResponse.json({});
      }),
    );

    renderSection();
    await userEvent.click(screen.getByRole("button", { name: "Create link" }));

    expect(
      await screen.findByText(
        "Enter the email address of the person you are inviting",
      ),
    ).toBeInTheDocument();
    expect(called).toBe(false);
  });

  it("refuses an address that is not one", async () => {
    renderSection();
    await userEvent.type(
      screen.getByLabelText("Email address"),
      "not-an-email",
    );
    await userEvent.click(screen.getByRole("button", { name: "Create link" }));

    expect(
      await screen.findByText("That doesn't look like an email address"),
    ).toBeInTheDocument();
  });

  it("sends the address and the role the inviter picked", async () => {
    let body: Record<string, unknown> | null = null;
    server.use(
      http.post("*/organizations/my/invitation-code", async ({ request }) => {
        body = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json({
          code: "ABCD1234",
          expires_at: dayFromNow,
          role: "manager",
          role_id: null,
          invited_email: "anna@example.com",
          email_sent: false,
        });
      }),
    );

    renderSection();
    await userEvent.type(
      screen.getByLabelText("Email address"),
      "anna@example.com",
    );
    await userEvent.selectOptions(screen.getByLabelText("Role"), "manager");
    await userEvent.click(screen.getByRole("button", { name: "Create link" }));

    await waitFor(() => expect(body).not.toBeNull());
    expect(body).toEqual({ role: "manager", email: "anna@example.com" });
  });

  it("offers to send when the organization has a mail server", async () => {
    // Promising "Send invitation" on an installation with no SMTP is a
    // promise the backend cannot keep.
    withOrgSmtp(true);
    renderSection();

    expect(
      await screen.findByRole("button", { name: "Send invitation" }),
    ).toBeInTheDocument();
  });

  it("hands over the link when there is no mail server", async () => {
    server.use(
      http.post("*/organizations/my/invitation-code", () =>
        HttpResponse.json({
          code: "ABCD1234",
          expires_at: dayFromNow,
          role: "user",
          role_id: null,
          invited_email: "anna@example.com",
          email_sent: false,
        }),
      ),
    );

    renderSection();
    await userEvent.type(
      screen.getByLabelText("Email address"),
      "anna@example.com",
    );
    await userEvent.click(screen.getByRole("button", { name: "Create link" }));

    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText("Invitation link")).toBeInTheDocument();
    expect(within(dialog).getByText(/join\?code=ABCD1234/)).toBeInTheDocument();
  });

  it("says a mailed invitation is queued, not delivered", async () => {
    // `email_sent` means the mail queue took the row. A configured but dead
    // SMTP takes it too, so "sent" was a claim the response never made — and
    // it hid the link the administrator would have needed instead.
    withOrgSmtp(true);
    server.use(
      http.post("*/organizations/my/invitation-code", () =>
        HttpResponse.json({
          code: "ABCD1234",
          expires_at: dayFromNow,
          role: "user",
          role_id: null,
          invited_email: "anna@example.com",
          email_sent: true,
        }),
      ),
    );

    renderSection();
    await userEvent.type(
      screen.getByLabelText("Email address"),
      "anna@example.com",
    );
    await userEvent.click(
      screen.getByRole("button", { name: "Send invitation" }),
    );

    await waitFor(() =>
      expect(toast.success).toHaveBeenCalledWith(
        "Invitation for anna@example.com queued for delivery",
      ),
    );
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("says a resent invitation is queued, not delivered", async () => {
    withOrgSmtp(true);
    server.use(
      http.get("*/organizations/my/invitations", () =>
        HttpResponse.json(onePage([PENDING_INVITATION])),
      ),
      http.post("*/organizations/my/invitations/:id/resend", () =>
        HttpResponse.json({ ...PENDING_INVITATION, email_sent: true }),
      ),
    );

    renderSection();

    const table = await screen.findByTestId("invitations-table");
    await userEvent.click(
      within(table).getByRole("button", {
        name: "Actions for the invitation to anna@example.com",
      }),
    );
    await userEvent.click(
      await screen.findByRole("button", { name: "Send again" }),
    );

    await waitFor(() =>
      expect(toast.success).toHaveBeenCalledWith(
        "Invitation for anna@example.com queued for delivery",
      ),
    );
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("hands over the link when a resend is not queued", async () => {
    // Extending the invitation is not a delivery: when nothing was queued the
    // administrator has to carry the link over themselves, as on creation.
    withOrgSmtp(true);
    server.use(
      http.get("*/organizations/my/invitations", () =>
        HttpResponse.json(onePage([PENDING_INVITATION])),
      ),
      http.post("*/organizations/my/invitations/:id/resend", () =>
        HttpResponse.json({ ...PENDING_INVITATION, email_sent: false }),
      ),
    );

    renderSection();

    const table = await screen.findByTestId("invitations-table");
    await userEvent.click(
      within(table).getByRole("button", {
        name: "Actions for the invitation to anna@example.com",
      }),
    );
    await userEvent.click(
      await screen.findByRole("button", { name: "Send again" }),
    );

    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText("Invitation link")).toBeInTheDocument();
    expect(within(dialog).getByText(/join\?code=LIVE5678/)).toBeInTheDocument();
    expect(within(dialog).getByText(/anna@example\.com/)).toBeInTheDocument();
  });

  it("leads each row with the person, not with the role", async () => {
    server.use(
      http.get("*/organizations/my/invitations", () =>
        HttpResponse.json(
          onePage([
            {
              id: "i1",
              code: "LIVE5678",
              role: "manager",
              role_id: null,
              is_used: false,
              expires_at: dayFromNow,
              created_at: hourAgo,
              invited_email: "anna@example.com",
              used_by_user_id: null,
              used_at: null,
            },
          ]),
        ),
      ),
    );

    renderSection();

    const table = await screen.findByTestId("invitations-table");
    const row = within(table).getByTestId("invitation-row");
    expect(within(row).getByText("anna@example.com")).toBeInTheDocument();
    expect(within(row).getByText("Waiting")).toBeInTheDocument();
  });

  it("separates an invitation whose mail was lost from one merely waiting", async () => {
    // Both are live and unredeemed, and the list could say only "Waiting"
    // about each — while one needs the link sent another way and the other
    // needs nothing at all.
    server.use(
      http.get("*/organizations/my/invitations", () =>
        HttpResponse.json(
          onePage([
            {
              ...PENDING_INVITATION,
              id: "lost",
              invited_email: "lost@example.com",
              email_status: "failed",
            },
            {
              ...PENDING_INVITATION,
              id: "arrived",
              invited_email: "arrived@example.com",
              email_status: "sent",
            },
          ]),
        ),
      ),
    );

    renderSection();

    const table = await screen.findByTestId("invitations-table");
    const rows = within(table).getAllByTestId("invitation-row");
    const lost = rows.find((row) =>
      within(row).queryByText("lost@example.com"),
    );
    const arrived = rows.find((row) =>
      within(row).queryByText("arrived@example.com"),
    );
    expect(within(lost!).getByText("Mail not delivered")).toBeInTheDocument();
    expect(within(arrived!).getByText("Waiting")).toBeInTheDocument();
  });

  it("folds expired invitations away until asked", async () => {
    // Thirteen dead rows out of sixteen was the screen that started this.
    server.use(
      http.get("*/organizations/my/invitations", () =>
        HttpResponse.json(
          onePage([
            {
              id: "i1",
              code: "LIVE5678",
              role: "user",
              role_id: null,
              is_used: false,
              expires_at: dayFromNow,
              created_at: hourAgo,
              invited_email: "anna@example.com",
              used_by_user_id: null,
              used_at: null,
            },
            {
              id: "i2",
              code: "GONE9999",
              role: "user",
              role_id: null,
              is_used: false,
              expires_at: hourAgo,
              created_at: hourAgo,
              invited_email: "tomasz@example.com",
              used_by_user_id: null,
              used_at: null,
            },
          ]),
        ),
      ),
    );

    renderSection();

    const table = await screen.findByTestId("invitations-table");
    expect(within(table).getByText("anna@example.com")).toBeInTheDocument();
    expect(
      within(table).queryByText("tomasz@example.com"),
    ).not.toBeInTheDocument();

    await userEvent.click(
      screen.getByRole("button", { name: "Show expired (1)" }),
    );
    expect(
      await within(table).findByText("tomasz@example.com"),
    ).toBeInTheDocument();
  });

  it("asks before withdrawing an invitation", async () => {
    let deleted: string | null = null;
    server.use(
      http.get("*/organizations/my/invitations", () =>
        HttpResponse.json(
          onePage([
            {
              id: "i1",
              code: "LIVE5678",
              role: "user",
              role_id: null,
              is_used: false,
              expires_at: dayFromNow,
              created_at: hourAgo,
              invited_email: "anna@example.com",
              used_by_user_id: null,
              used_at: null,
            },
          ]),
        ),
      ),
      http.delete("*/organizations/my/invitations/:id", ({ params }) => {
        deleted = params.id as string;
        return new HttpResponse(null, { status: 204 });
      }),
    );

    renderSection();

    const table = await screen.findByTestId("invitations-table");
    await userEvent.click(
      within(table).getByRole("button", {
        name: "Actions for the invitation to anna@example.com",
      }),
    );
    await userEvent.click(
      await screen.findByRole("button", { name: "Revoke" }),
    );

    // The menu item opens a confirmation; nothing has been withdrawn yet.
    expect(deleted).toBeNull();
    await userEvent.click(
      await screen.findByRole("button", { name: "Revoke" }),
    );
    await waitFor(() => expect(deleted).toBe("i1"));
  });

  it("names the custom role on a listed invitation", async () => {
    server.use(
      http.get("*/roles", () =>
        HttpResponse.json(
          onePage([
            {
              id: "role-xyz",
              organization_id: "org-1",
              name: "Night Shift",
              permissions: ["items:read"],
              is_system: false,
              created_at: null,
            },
          ]),
        ),
      ),
      http.get("*/organizations/my/invitations", () =>
        HttpResponse.json(
          onePage([
            {
              id: "i9",
              code: "CUST2345",
              role: "user",
              role_id: "role-xyz",
              is_used: false,
              expires_at: dayFromNow,
              created_at: hourAgo,
              invited_email: "anna@example.com",
              used_by_user_id: null,
              used_at: null,
            },
          ]),
        ),
      ),
    );

    renderSection();

    const table = await screen.findByTestId("invitations-table");
    const row = within(table).getByTestId("invitation-row");
    expect(within(row).getByText("Night Shift")).toBeInTheDocument();
  });

  it("says so when nothing has been issued", async () => {
    renderSection();

    expect(
      await screen.findByText("No invitation has been issued yet."),
    ).toBeInTheDocument();
  });

  it("says the list could not be read instead of claiming none was issued", async () => {
    // "No invitation has been issued yet" is a claim about the organization,
    // and a failed request cannot make it: the section unpacked its read with
    // a default empty array and never looked at `isError`.
    server.use(
      http.get(
        "*/organizations/my/invitations",
        () => new HttpResponse(null, { status: 500 }),
      ),
    );

    renderSection();

    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(
      await screen.findByRole("button", { name: /try again/i }),
    ).toBeInTheDocument();
    expect(
      screen.queryByText("No invitation has been issued yet."),
    ).not.toBeInTheDocument();
  });

  it("marks a custom role on the list", async () => {
    // A custom role is named by whoever wrote it, so on the list its name
    // sat beside "Administrator" and "Member" with nothing saying it is not
    // a fourth built-in level.
    server.use(
      http.get("*/roles", () =>
        HttpResponse.json(
          onePage([
            {
              id: "role-1",
              name: "Warehouse lead",
              is_system: false,
              base_level: "user",
              permissions: [],
            },
          ]),
        ),
      ),
      http.get("*/organizations/my/invitations", () =>
        HttpResponse.json(
          onePage([
            {
              id: "inv-1",
              code: "ABCD1234",
              role: "user",
              role_id: "role-1",
              is_used: false,
              expires_at: dayFromNow,
              created_at: hourAgo,
              invited_email: "lead@example.com",
              used_by_user_id: null,
              used_at: null,
            },
          ]),
        ),
      ),
    );

    renderSection();

    // The picker also lists it, under its own optgroup — the list is what
    // this is about.
    const table = await screen.findByTestId("invitations-table");
    expect(within(table).getByText("Warehouse lead")).toBeInTheDocument();
    expect(within(table).getByText("Custom")).toBeInTheDocument();
  });
});
