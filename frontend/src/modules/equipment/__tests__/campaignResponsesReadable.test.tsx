import React, { useState } from "react";
import { render, screen, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { http, HttpResponse } from "msw";
import { server } from "@/test/mocks/server";
import { signInWith, signOut } from "@/test/auth";
import { ModulesProvider } from "@/contexts/ModulesContext";
import {
  PageHeaderContext,
  type PageHeaderData,
} from "@/hooks/useModulePageHeader";
import CampaignDetailPage from "../pages/CampaignDetailPage";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

/**
 * A dispute reached the administrator as "[DAMAGED] The hinge is cracked":
 * the machine's token in square brackets, English in every installation,
 * and the asset beside it plain text, so acting on the dispute started with
 * a search of the asset list by serial number.
 */
const CAMPAIGN_ID = "3f0c2a8e-1b2c-4d5e-8f90-a1b2c3d4e5f6";

const disputed = {
  id: "resp-1",
  campaign_id: CAMPAIGN_ID,
  assignment_id: "asg-1",
  assignee_email: "nina@example.com",
  assignee_name: "Nina",
  item_name: "ThinkPad T14",
  serial_number: "SN-9911",
  items: [
    {
      id: "ri-1",
      response_id: "resp-1",
      assignment_id: "asg-1",
      item_id: "itm-77",
      item_name: "ThinkPad T14",
      serial_number: "SN-9911",
      status: "DISPUTED",
      dispute_type: "DAMAGED",
      dispute_reason: "The hinge is cracked",
      returned: false,
    },
  ],
  status: "DISPUTED",
  responded_at: "2026-10-20T10:00:00Z",
  dispute_type: "DAMAGED",
  dispute_reason: "The hinge is cracked",
  email_sent_at: null,
  reminder_sent_at: null,
  created_at: "2026-10-19T10:00:00Z",
  closed_reason: null,
  assets_returned: false,
};

const campaign = {
  id: CAMPAIGN_ID,
  organization_id: "org-1",
  name: "Annual Audit 2026",
  description: null,
  scope_type: "ALL" as const,
  scope_filter_id: null,
  launched_at: "2026-10-19T10:00:00Z",
  deadline: "2026-12-31T00:00:00Z",
  reminder_days_before: 7,
  last_reminder_sent_at: null,
  status: "ACTIVE" as const,
  email_subject: null,
  email_body: null,
  created_by: "user-1",
  created_at: "2026-10-01T00:00:00Z",
  updated_at: "2026-10-01T00:00:00Z",
  stats: { total: 1, confirmed: 0, disputed: 1, pending: 0, expired: 0 },
  responses: [disputed],
};

function HeaderHost({ children }: { children: React.ReactNode }) {
  const [data, setData] = useState<PageHeaderData>({});
  return (
    <PageHeaderContext.Provider value={{ data, setHeader: setData }}>
      {children}
    </PageHeaderContext.Provider>
  );
}

beforeEach(() => {
  signInWith(["equipment:read", "equipment:write"]);
  server.use(
    http.get(`/api/v1/equipment/campaigns/${CAMPAIGN_ID}`, () =>
      HttpResponse.json(campaign),
    ),
  );
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
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
});

afterEach(() => {
  signOut();
});

describe("a disputed response on the campaign page", () => {
  it("names the dispute type in words, not as a bracketed token", async () => {
    await screen.findAllByText(/The hinge is cracked/);

    expect(screen.queryByText(/\[DAMAGED\]/)).not.toBeInTheDocument();
    expect(screen.getAllByText("Damaged:").length).toBeGreaterThan(0);
  });

  it("links the asset to its own page", async () => {
    const [table] = await screen.findAllByRole("table");

    const link = within(table).getByRole("link", { name: /ThinkPad T14/ });
    expect(link).toHaveAttribute("href", "/equipment/itm-77");
  });
});
