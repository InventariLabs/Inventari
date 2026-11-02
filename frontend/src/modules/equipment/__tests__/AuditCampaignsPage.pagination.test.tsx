import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen } from "@/test/utils";
import userEvent from "@testing-library/user-event";
import { server } from "@/test/mocks/server";
import { http, HttpResponse } from "msw";
import { PageHeaderContext } from "@/hooks/useModulePageHeader";
import AuditCampaignsPage from "../pages/AuditCampaignsPage";
import { useAuthStore } from "@/store/authStore";
import type { User } from "@/types";
import { onePage } from "@/test/mocks/page";

/**
 * The campaigns list endpoint returns the full list; the page used to render
 * every campaign. Client-side pagination keeps the DOM bounded at tens of
 * records (an acceptable scale for campaigns).
 */

const makeCampaign = (i: number) => ({
  id: `campaign-${i}`,
  organization_id: "org-1",
  name: `Campaign ${i}`,
  description: null,
  scope_type: "ALL",
  scope_filter_id: null,
  launched_at: null,
  deadline: "2026-12-31T00:00:00Z",
  reminder_days_before: 3,
  last_reminder_sent_at: null,
  status: "DRAFT",
  email_subject: null,
  email_body: null,
  created_by: "user-1",
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
});

const twentyFiveCampaigns = Array.from({ length: 25 }, (_, i) =>
  makeCampaign(i + 1),
);

describe("AuditCampaignsPage — the empty state explains the word", () => {
  it("says what an attestation is before asking anyone to start one", async () => {
    // "No attestations yet." named nothing: not what an attestation is,
    // not what "New attestation" would start. Of the four equipment list
    // screens it was the only one whose empty state explained nothing,
    // and attestation was the least self-evident word of the four.
    server.use(
      http.get("/api/v1/equipment/campaigns", () =>
        HttpResponse.json(onePage([])),
      ),
    );
    render(
      <PageHeaderContext.Provider value={{ data: {}, setHeader: () => {} }}>
        <AuditCampaignsPage />
      </PageHeaderContext.Provider>,
    );

    expect(await screen.findByText("No attestations yet.")).toBeInTheDocument();
    expect(screen.getByText(/holder of an asset/i)).toBeInTheDocument();
  });

  it("does not point a reader without write rights at a button they do not have", async () => {
    // The default signed-in account here holds no permissions, so the page
    // renders no "New attestation" — and the description used to tell that
    // reader "Start with New attestation above" anyway.
    server.use(
      http.get("/api/v1/equipment/campaigns", () =>
        HttpResponse.json(onePage([])),
      ),
    );
    render(
      <PageHeaderContext.Provider value={{ data: {}, setHeader: () => {} }}>
        <AuditCampaignsPage />
      </PageHeaderContext.Provider>,
    );

    expect(
      await screen.findByText(/reserved for accounts with editing rights/i),
    ).toBeInTheDocument();
    expect(
      screen.queryByText(/Start with New attestation/),
    ).not.toBeInTheDocument();
  });

  it("still names the action for a reader who can start one", async () => {
    useAuthStore.setState({
      user: {
        id: "1",
        full_name: "Admin",
        email: "admin@example.com",
        preferred_language: "en",
        role: "admin",
      } as User,
    });
    server.use(
      http.get("/api/v1/equipment/campaigns", () =>
        HttpResponse.json(onePage([])),
      ),
    );
    render(
      <PageHeaderContext.Provider value={{ data: {}, setHeader: () => {} }}>
        <AuditCampaignsPage />
      </PageHeaderContext.Provider>,
    );

    expect(
      await screen.findByText(/Start with New attestation above/),
    ).toBeInTheDocument();
  });
});

describe("AuditCampaignsPage — pagination", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    server.use(
      http.get("/api/v1/equipment/campaigns", () =>
        HttpResponse.json(onePage(twentyFiveCampaigns)),
      ),
    );
  });

  it("renders only the first page of campaigns with a pagination bar", async () => {
    render(
      <PageHeaderContext.Provider value={{ data: {}, setHeader: () => {} }}>
        <AuditCampaignsPage />
      </PageHeaderContext.Provider>,
    );

    expect(await screen.findByText("Campaign 1")).toBeInTheDocument();
    expect(screen.getByText("Campaign 10")).toBeInTheDocument();
    expect(screen.queryByText("Campaign 11")).not.toBeInTheDocument();
    expect(screen.getByText("1 / 3")).toBeInTheDocument();
  });

  it("pages forward to the next batch of campaigns", async () => {
    const user = userEvent.setup();
    render(
      <PageHeaderContext.Provider value={{ data: {}, setHeader: () => {} }}>
        <AuditCampaignsPage />
      </PageHeaderContext.Provider>,
    );

    await screen.findByText("Campaign 1");
    await user.click(screen.getByRole("button", { name: /next/i }));

    expect(await screen.findByText("Campaign 11")).toBeInTheDocument();
    expect(screen.getByText("2 / 3")).toBeInTheDocument();
    expect(screen.queryByText("Campaign 1")).not.toBeInTheDocument();
  });
});
