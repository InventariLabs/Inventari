import React, { useState } from "react";
import {
  render,
  screen,
  waitFor,
  fireEvent,
  within,
} from "@testing-library/react";
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
import { onePage } from "@/test/mocks/page";

// These pages hide their write actions from an account that cannot write,
// so a spec about the actions has to say who is looking at them.
beforeEach(() => {
  signInWith([
    "equipment:read",
    "equipment:write",
    "items:read",
    "locations:read",
    "locations:write",
    "categories:read",
    "categories:write",
  ]);
});

afterEach(() => {
  signOut();
});

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

const CAMPAIGN_ID = "3f0c2a8e-1b2c-4d5e-8f90-a1b2c3d4e5f6";
const STORAGE_ID = "7a1b2c3d-4e5f-4061-8273-9a0b1c2d3e4f";

const draftCampaign = {
  id: CAMPAIGN_ID,
  organization_id: "org-1",
  name: "Annual Audit 2026",
  description: null,
  scope_type: "STORAGE" as const,
  scope_filter_id: STORAGE_ID,
  launched_at: null,
  deadline: "2026-12-31T00:00:00Z",
  reminder_days_before: 7,
  last_reminder_sent_at: null,
  status: "DRAFT" as const,
  email_subject: "Please confirm the equipment you hold",
  email_body: null,
  created_by: "user-1",
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
  stats: { total: 0, confirmed: 0, disputed: 0, pending: 0, expired: 0 },
  responses: [],
};

/** Renders whatever the page puts in the module header, as the shell does. */
function HeaderHost({ children }: { children: React.ReactNode }) {
  const [data, setData] = useState<PageHeaderData>({});
  return (
    <PageHeaderContext.Provider value={{ data, setHeader: setData }}>
      <div data-testid="header">
        {data.statusBadge}
        {data.actions}
      </div>
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

/**
 * A campaign sends email outside the organization. Its detail screen told the
 * reader to launch it, offered no way to do so, and showed none of what the
 * creation dialog had asked for — so there was nothing to check first.
 */
describe("campaign detail before the campaign runs", () => {
  beforeEach(() => {
    server.use(
      http.get(`/api/v1/equipment/campaigns/${CAMPAIGN_ID}`, () =>
        HttpResponse.json(draftCampaign),
      ),
      http.get("/api/v1/locations", () =>
        HttpResponse.json(onePage([{ id: STORAGE_ID, name: "Server Room A" }])),
      ),
    );
  });

  it("shows what the campaign will do", async () => {
    renderPage();

    expect(await screen.findByText("Attestation setup")).toBeInTheDocument();
    expect(await screen.findByText(/Server Room A/)).toBeInTheDocument();
    expect(screen.getByText("7")).toBeInTheDocument();
    expect(
      screen.getByText("Please confirm the equipment you hold"),
    ).toBeInTheDocument();
  });

  it("can be launched from its own screen, after confirming", async () => {
    let launched = false;
    server.use(
      http.post(`/api/v1/equipment/campaigns/${CAMPAIGN_ID}/launch`, () => {
        launched = true;
        return HttpResponse.json({
          responses_created: 2,
          skipped_no_email: 0,
          emails_sent: 2,
          emails_failed: 0,
        });
      }),
    );

    renderPage();

    const header = await screen.findByTestId("header");
    fireEvent.click(
      await within(header).findByRole("button", { name: /Launch/ }),
    );

    const dialog = await screen.findByRole("alertdialog");
    fireEvent.click(within(dialog).getByRole("button", { name: /^Launch$/ }));

    await waitFor(() => expect(launched).toBe(true));
  });

  it("names the status instead of printing its code", async () => {
    renderPage();

    const header = await screen.findByTestId("header");
    await waitFor(() =>
      expect(within(header).getByText("Draft")).toBeInTheDocument(),
    );
    expect(within(header).queryByText("DRAFT")).not.toBeInTheDocument();
  });
});
