/**
 * Send Reminders answered `{reminders_sent: 0}` with an unchanged page, so the
 * admin believed the people had been chased; and a response whose asset was
 * returned stayed "Awaiting reply" while the person's own link said
 * "Already Returned". The page now says what a run did, and why it did no more,
 * and shows a returned response as returned.
 */
import React, { useState } from "react";
import {
  render,
  screen,
  fireEvent,
  waitFor,
  within,
} from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { http, HttpResponse } from "msw";
import { toast } from "sonner";
import { server } from "@/test/mocks/server";
import { signInWith, signOut } from "@/test/auth";
import { ModulesProvider } from "@/contexts/ModulesContext";
import {
  PageHeaderContext,
  type PageHeaderData,
} from "@/hooks/useModulePageHeader";
import CampaignDetailPage from "../pages/CampaignDetailPage";

vi.mock("sonner", () => ({
  toast: {
    success: vi.fn(),
    error: vi.fn(),
    info: vi.fn(),
    warning: vi.fn(),
  },
}));

const CAMPAIGN_ID = "3f0c2a8e-1b2c-4d5e-8f90-a1b2c3d4e5f6";

const response = (over: Record<string, unknown> = {}) => ({
  id: "resp-1",
  campaign_id: CAMPAIGN_ID,
  assignment_id: null,
  assignee_email: "ava@example.com",
  assignee_name: "Ava Brennan",
  item_name: "Laptop",
  serial_number: null,
  items: [],
  status: "PENDING",
  assets_returned: false,
  responded_at: null,
  dispute_reason: null,
  dispute_type: null,
  email_sent_at: null,
  reminder_sent_at: null,
  created_at: "2026-10-01T00:00:00Z",
  closed_reason: null,
  ...over,
});

const campaign = (responses: unknown[], stats: Record<string, number>) => ({
  id: CAMPAIGN_ID,
  organization_id: "org-1",
  name: "Autumn equipment check",
  description: null,
  scope_type: "ALL",
  scope_filter_id: null,
  launched_at: "2026-10-01T00:00:00Z",
  deadline: "2026-12-31T00:00:00Z",
  reminder_days_before: 3,
  last_reminder_sent_at: null,
  status: "ACTIVE",
  email_subject: null,
  email_body: null,
  created_by: "user-1",
  created_at: "2026-10-01T00:00:00Z",
  updated_at: "2026-10-01T00:00:00Z",
  stats: {
    total: 0,
    confirmed: 0,
    disputed: 0,
    pending: 0,
    expired: 0,
    returned: 0,
    ...stats,
  },
  responses,
});

function HeaderHost({ children }: { children: React.ReactNode }) {
  const [data, setData] = useState<PageHeaderData>({});
  return (
    <PageHeaderContext.Provider value={{ data, setHeader: setData }}>
      <div data-testid="header">{data.actions}</div>
      {children}
    </PageHeaderContext.Provider>
  );
}

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <ModulesProvider>
        <MemoryRouter initialEntries={[`/equipment/campaigns/${CAMPAIGN_ID}`]}>
          <HeaderHost>
            <Routes>
              <Route
                path="/equipment/campaigns/:id"
                element={<CampaignDetailPage />}
              />
            </Routes>
          </HeaderHost>
        </MemoryRouter>
      </ModulesProvider>
    </QueryClientProvider>,
  );
}

function serve(run: Record<string, unknown>) {
  server.use(
    http.get(`/api/v1/equipment/campaigns/${CAMPAIGN_ID}`, () =>
      HttpResponse.json(campaign([response()], { total: 1, pending: 1 })),
    ),
    http.post(`/api/v1/equipment/campaigns/${CAMPAIGN_ID}/remind`, () =>
      HttpResponse.json({
        reminders_sent: 0,
        awaiting_reply: 1,
        reminded_recently: 0,
        not_delivered: 0,
        email_unavailable: false,
        ...run,
      }),
    ),
  );
}

async function pressSendReminders() {
  fireEvent.click(
    await screen.findByRole("button", { name: "Send Reminders" }),
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  signInWith(["equipment:read", "equipment:write", "items:read"]);
});

afterEach(() => signOut());

describe("Send Reminders says what it did", () => {
  it("counts the reminders that went out", async () => {
    serve({ reminders_sent: 2, awaiting_reply: 2 });
    renderPage();
    await pressSendReminders();
    await waitFor(() =>
      expect(toast.success).toHaveBeenCalledWith("2 reminders sent", undefined),
    );
  });

  it("says there is no outgoing e-mail when that is why nothing went out", async () => {
    serve({ email_unavailable: true });
    renderPage();
    await pressSendReminders();
    await waitFor(() =>
      expect(toast.warning).toHaveBeenCalledWith(
        expect.stringMatching(/does not send email/),
      ),
    );
  });

  it("names the 24-hour rule when everyone was just reminded", async () => {
    serve({ reminded_recently: 1 });
    renderPage();
    await pressSendReminders();
    await waitFor(() =>
      expect(toast.info).toHaveBeenCalledWith(
        expect.stringMatching(/last 24 hours/),
      ),
    );
  });

  it("says nobody is waiting when nobody is", async () => {
    serve({ awaiting_reply: 0 });
    renderPage();
    await pressSendReminders();
    await waitFor(() =>
      expect(toast.info).toHaveBeenCalledWith(
        expect.stringMatching(/nobody is still waiting/),
      ),
    );
  });
});

describe("a returned asset is not a person who has not answered", () => {
  it("shows the response as returned and counts it apart from pending", async () => {
    server.use(
      http.get(`/api/v1/equipment/campaigns/${CAMPAIGN_ID}`, () =>
        HttpResponse.json(
          campaign([response({ assets_returned: true })], {
            total: 1,
            returned: 1,
          }),
        ),
      ),
    );
    renderPage();

    expect((await screen.findAllByText("Returned")).length).toBeGreaterThan(0);
    expect(screen.queryByText("Awaiting reply")).not.toBeInTheDocument();
    expect(
      screen.getByText(
        (_, el) =>
          el?.tagName === "SPAN" && el.textContent === "Awaiting reply: 0",
      ),
    ).toBeInTheDocument();
  });
});

describe("Complete asks first, here as on the list", () => {
  it("closes the campaign only after the question is answered", async () => {
    let completed = 0;
    server.use(
      http.get(`/api/v1/equipment/campaigns/${CAMPAIGN_ID}`, () =>
        HttpResponse.json(campaign([response()], { total: 1, pending: 1 })),
      ),
      http.post(`/api/v1/equipment/campaigns/${CAMPAIGN_ID}/complete`, () => {
        completed += 1;
        return HttpResponse.json(campaign([], {}));
      }),
    );
    renderPage();

    fireEvent.click(await screen.findByRole("button", { name: "Complete" }));
    expect(
      await screen.findByText("Complete attestation?"),
    ).toBeInTheDocument();
    expect(completed).toBe(0);

    const dialog = screen.getByRole("alertdialog");
    fireEvent.click(within(dialog).getByRole("button", { name: "Complete" }));
    await waitFor(() => expect(completed).toBe(1));
  });
});

describe("an attestation where no email goes out", () => {
  it("says so before the launch and names who was not asked after it", async () => {
    let launched = 0;
    server.use(
      http.get("/api/v1/organizations/my", () =>
        HttpResponse.json({ id: "org-1", name: "Org", can_send_email: false }),
      ),
      http.get(`/api/v1/equipment/campaigns/${CAMPAIGN_ID}`, () =>
        HttpResponse.json({ ...campaign([], {}), status: "DRAFT" }),
      ),
      http.get("/api/v1/equipment/campaigns/scope-preview", () =>
        HttpResponse.json({ assets: 3, people: 2, without_email: 1 }),
      ),
      http.post(`/api/v1/equipment/campaigns/${CAMPAIGN_ID}/launch`, () => {
        launched += 1;
        return HttpResponse.json({
          responses_created: 2,
          skipped_no_email: 1,
          skipped_people: ["Bob Without Mail"],
          emails_sent: 0,
          emails_failed: 0,
          email_unavailable: true,
        });
      }),
    );
    renderPage();

    fireEvent.click(await screen.findByRole("button", { name: "Launch" }));
    const dialog = await screen.findByRole("alertdialog");
    expect(dialog).toHaveTextContent(/does not send email/);
    expect(dialog).toHaveTextContent(/1 asset is checked out without an email/);

    fireEvent.click(within(dialog).getByRole("button", { name: "Launch" }));
    await waitFor(() => expect(launched).toBe(1));
    await waitFor(() =>
      expect(toast.warning).toHaveBeenCalledWith(
        expect.stringMatching(/nobody was emailed/),
        { description: expect.stringMatching(/Bob Without Mail/) },
      ),
    );
  });

  it("gives out the link of a person no invitation reached", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.assign(navigator, { clipboard: { writeText } });
    server.use(
      http.get(`/api/v1/equipment/campaigns/${CAMPAIGN_ID}`, () =>
        HttpResponse.json(campaign([response()], { total: 1, pending: 1 })),
      ),
      http.get(
        `/api/v1/equipment/campaigns/${CAMPAIGN_ID}/responses/resp-1/link`,
        () =>
          HttpResponse.json({
            url: "https://app.example/public/attestation/tok",
          }),
      ),
    );
    renderPage();

    fireEvent.click(
      (await screen.findAllByRole("button", { name: "Copy link" }))[0],
    );

    await waitFor(() =>
      expect(writeText).toHaveBeenCalledWith(
        "https://app.example/public/attestation/tok",
      ),
    );
    expect(toast.success).toHaveBeenCalledWith(
      "Link copied — hand it to the person.",
    );
  });
});
