import React from "react";
import {
  render,
  screen,
  waitFor,
  fireEvent,
  within,
} from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { http, HttpResponse } from "msw";
import { toast } from "sonner";
import { server } from "@/test/mocks/server";
import { signInWith, signOut } from "@/test/auth";
import { withModules } from "@/test/moduleList";
import { ModulesProvider } from "@/contexts/ModulesContext";
import AuditCampaignsPage from "../pages/AuditCampaignsPage";
import { onePage } from "@/test/mocks/page";

// These pages hide their write actions from an account that cannot write,
// so a spec about the actions has to say who is looking at them.
beforeEach(() => {
  withModules("equipment");
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

vi.mock("@/hooks/useModulePageHeader", () => ({
  useModulePageHeader: () => ({ setHeader: vi.fn() }),
}));

const CAMPAIGN_ID = "8c5f2a1e-7d4b-4c3a-9f8e-1b2c3d4e5f60";

const draftCampaign = {
  id: CAMPAIGN_ID,
  organization_id: "org-1",
  name: "Annual Audit 2026",
  description: null,
  scope_type: "ALL" as const,
  scope_filter_id: null,
  launched_at: null,
  deadline: "2026-12-31T00:00:00Z",
  reminder_days_before: 7,
  last_reminder_sent_at: null,
  status: "DRAFT" as const,
  email_subject: null,
  email_body: null,
  created_by: "user-1",
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};

const createWrapper = () => {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={queryClient}>
      <ModulesProvider>
        <MemoryRouter>{children}</MemoryRouter>
      </ModulesProvider>
    </QueryClientProvider>
  );
};

/**
 * The walkthrough launched a campaign whose scope held nothing that was
 * checked out. The API refused, the screen showed no change at all, and the
 * reader left believing the survey had gone out.
 */
describe("launching a campaign that has nothing to survey", () => {
  beforeEach(() => {
    vi.mocked(toast.error).mockClear();
    server.use(
      http.get("/api/v1/equipment/campaigns", () =>
        HttpResponse.json(onePage([draftCampaign])),
      ),
      http.post(`/api/v1/equipment/campaigns/${CAMPAIGN_ID}/launch`, () =>
        HttpResponse.json(
          { detail: "No active assignments found for the configured scope" },
          { status: 400 },
        ),
      ),
    );
  });

  it("tells the reader why nothing was sent", async () => {
    render(<AuditCampaignsPage />, { wrapper: createWrapper() });

    await screen.findByText("Annual Audit 2026");
    fireEvent.click(screen.getByRole("button", { name: /^Launch$/ }));

    const dialog = await screen.findByRole("alertdialog");
    fireEvent.click(within(dialog).getByRole("button", { name: /^Launch$/ }));

    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith(
        "No active assignments found for the configured scope",
      ),
    );
  });
});

/**
 * The other half of the same walkthrough: the reader used to learn that there
 * was nobody in scope only from the refusal behind the irreversible gate. The
 * count is fetched before the dialog now, and a scope covering nobody is
 * answered with where to fill it in.
 */
describe("launching a campaign whose scope covers nobody", () => {
  let launched = false;

  beforeEach(() => {
    launched = false;
    server.use(
      http.get("/api/v1/equipment/campaigns", () =>
        HttpResponse.json(onePage([draftCampaign])),
      ),
      http.get("/api/v1/equipment/campaigns/scope-preview", () =>
        HttpResponse.json({ assets: 0, people: 0, without_email: 0 }),
      ),
      http.post(`/api/v1/equipment/campaigns/${CAMPAIGN_ID}/launch`, () => {
        launched = true;
        return HttpResponse.json({ responses_created: 0 });
      }),
    );
  });

  it("does not offer the send without saying where the people come from", async () => {
    render(<AuditCampaignsPage />, { wrapper: createWrapper() });

    await screen.findByText("Annual Audit 2026");
    fireEvent.click(screen.getByRole("button", { name: /^Launch$/ }));

    const dialog = await screen.findByRole("alertdialog");
    expect(within(dialog).getByText("Nobody to attest")).toBeInTheDocument();
    expect(
      within(dialog).getByText(/Assign an asset first/i),
    ).toBeInTheDocument();
    expect(
      within(dialog).queryByRole("button", { name: /^Launch$/ }),
    ).not.toBeInTheDocument();
    expect(
      within(dialog).getByRole("button", { name: "Go to assignments" }),
    ).toBeInTheDocument();
    expect(launched).toBe(false);
  });
});
