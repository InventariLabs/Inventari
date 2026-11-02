/**
 * regression: header action buttons used to stay live while their own
 * request was in flight.
 *
 * The page builds the header JSX inside a `useEffect`. The values that JSX
 * reads are captured when the effect last ran, and the effect's dependency
 * list omitted the mutation objects (a new reference every render — putting
 * the object in would loop the effect). The booleans inside those objects
 * went stale with them: `isPending` stayed `false` in the captured JSX, so
 * "Send Reminders" and "Request Approval" could be clicked twice and the
 * second request went out. The fix passes booleans and stable `mutate`
 * functions into the header and keeps the booleans in the deps.
 */
import React, { useState } from "react";
import {
  act,
  render,
  screen,
  waitFor,
  fireEvent,
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
import AssetDetailPage from "../pages/AssetDetailPage";
import { onePage } from "@/test/mocks/page";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

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

/** A promise the test resolves by hand, to hold a request in flight. */
function deferred() {
  let resolve!: () => void;
  const promise = new Promise<void>((r) => {
    resolve = r;
  });
  return { promise, resolve };
}

/** Mirrors ModuleShell: keeps the header data and renders its actions. */
function HeaderHost({ children }: { children: React.ReactNode }) {
  const [data, setData] = useState<PageHeaderData>({});
  return (
    <PageHeaderContext.Provider value={{ data, setHeader: setData }}>
      <div data-testid="header">{data.actions}</div>
      {children}
    </PageHeaderContext.Provider>
  );
}

function renderPage(
  initialEntry: string,
  path: string,
  element: React.ReactNode,
) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <ModulesProvider>
        <MemoryRouter initialEntries={[initialEntry]}>
          <HeaderHost>
            <Routes>
              <Route path={path} element={element} />
            </Routes>
          </HeaderHost>
        </MemoryRouter>
      </ModulesProvider>
    </QueryClientProvider>,
  );
}

const CAMPAIGN_ID = "3f0c2a8e-1b2c-4d5e-8f90-a1b2c3d4e5f6";

const activeCampaign = {
  id: CAMPAIGN_ID,
  organization_id: "org-1",
  name: "Annual Audit 2026",
  description: null,
  scope_type: "ALL" as const,
  scope_filter_id: null,
  launched_at: "2026-08-20T00:00:00Z",
  deadline: "2026-12-31T00:00:00Z",
  reminder_days_before: 7,
  last_reminder_sent_at: null,
  status: "ACTIVE" as const,
  email_subject: null,
  email_body: null,
  created_by: "user-1",
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
  stats: { total: 1, confirmed: 0, disputed: 0, pending: 1, expired: 0 },
  responses: [],
};

describe("a header button blocks while its own request is in flight", () => {
  it("Send Reminders cannot put a second batch in flight", async () => {
    const gate = deferred();
    let posts = 0;
    server.use(
      http.get(`/api/v1/equipment/campaigns/${CAMPAIGN_ID}`, () =>
        HttpResponse.json(activeCampaign),
      ),
      http.post(
        `/api/v1/equipment/campaigns/${CAMPAIGN_ID}/remind`,
        async () => {
          posts += 1;
          await gate.promise;
          return HttpResponse.json({ reminders_sent: 1 });
        },
      ),
    );

    renderPage(
      `/equipment/campaigns/${CAMPAIGN_ID}`,
      "/equipment/campaigns/:id",
      <CampaignDetailPage />,
    );

    fireEvent.click(
      await screen.findByRole("button", { name: "Send Reminders" }),
    );
    await screen.findByRole("button", { name: "Sending…" });
    expect(screen.getByRole("button", { name: "Sending…" })).toBeDisabled();

    fireEvent.click(screen.getByRole("button", { name: "Sending…" }));
    await new Promise((r) => setTimeout(r, 30));
    expect(posts).toBe(1);

    gate.resolve();
    await screen.findByRole("button", { name: "Send Reminders" });
  });

  const ITEM_ID = "ec6be09a-90ba-449d-a45b-6217ef627d37";

  it("Request Approval cannot be sent twice from a second click", async () => {
    const gate = deferred();
    let posts = 0;
    server.use(
      http.get(`/api/v1/items/${ITEM_ID}`, () =>
        HttpResponse.json({
          id: ITEM_ID,
          name: "HP EliteBook",
          brand: "HP",
          barcode: null,
          status: "ACTIVE",
          category_id: "cat-1",
          location_id: "loc-1",
          context_tag: "equipment",
          quantity: 1,
          added_date: "2024-01-01T00:00:00Z",
          created_at: "2024-01-01T00:00:00Z",
          updated_at: "2024-01-01T00:00:00Z",
          metadata: {
            equipment: {
              equipment_status: "MAINTENANCE",
              serial_number: "SN-123",
            },
          },
        }),
      ),
      http.get(`/api/v1/equipment/assignments/item/${ITEM_ID}`, () =>
        HttpResponse.json(onePage([])),
      ),
      http.get(`/api/v1/equipment/${ITEM_ID}/approval-status`, () =>
        HttpResponse.json({
          has_workflow: true,
          request_id: null,
          status: null,
        }),
      ),
      http.get(`/api/v1/equipment/${ITEM_ID}/valuation`, () =>
        HttpResponse.json({}),
      ),
      http.get(`/api/v1/equipment/${ITEM_ID}/attachments`, () =>
        HttpResponse.json(onePage([])),
      ),
      http.post(`/api/v1/equipment/${ITEM_ID}/request-approval`, async () => {
        posts += 1;
        await gate.promise;
        return HttpResponse.json({ request_id: "req-1", status: "PENDING" });
      }),
    );

    renderPage(`/equipment/${ITEM_ID}`, "/equipment/:id", <AssetDetailPage />);

    // The request names the checkout it asks for, so it is sent from the
    // checkout dialog; its send button is the one that must block.
    fireEvent.click(
      await screen.findByRole("button", { name: "Request Approval" }),
    );
    fireEvent.change(await screen.findByLabelText(/assigned to \(name\)/i), {
      target: { value: "Kasia Kowalska" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Send for approval" }));

    // In flight: the same button, now disabled.
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "Send for approval" }),
      ).toBeDisabled(),
    );
    fireEvent.click(screen.getByRole("button", { name: "Send for approval" }));
    // Inside act(): the dialog's own queries (the directory search behind
    // the typed name) may answer during the wait, and an answer outside
    // act() warned under a loaded run.
    await act(async () => {
      await new Promise((r) => setTimeout(r, 30));
    });
    expect(posts).toBe(1);

    // Let the request land and the dialog close inside the test: left to
    // settle after it, the updates warned outside act() under a loaded run.
    gate.resolve();
    await waitFor(() =>
      expect(
        screen.queryByRole("button", { name: "Send for approval" }),
      ).not.toBeInTheDocument(),
    );
  });
});
