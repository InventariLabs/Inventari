import { describe, expect, it, beforeEach, afterEach } from "vitest";
import userEvent from "@testing-library/user-event";
import { render, screen, within } from "@/test/utils";
import { server } from "@/test/mocks/server";
import { http, HttpResponse } from "msw";
import { signInWith, signOut } from "@/test/auth";
import { ModulesProvider } from "@/contexts/ModulesContext";
import { PageHeaderContext } from "@/hooks/useModulePageHeader";
import AuditCampaignsPage from "../pages/AuditCampaignsPage";
import { onePage } from "@/test/mocks/page";

/**
 * Complete closed a campaign over answers still out without saying how many,
 * and a draft showed "people: 2" only inside the Launch confirmation — the
 * audience was a number until after the mail had gone.
 */
const base = {
  organization_id: "org-1",
  description: null,
  scope_type: "ALL",
  scope_filter_id: null,
  deadline: "2026-12-31T00:00:00Z",
  reminder_days_before: 3,
  last_reminder_sent_at: null,
  email_subject: null,
  email_body: null,
  created_by: "user-1",
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};

const response = (id: string, status: string) => ({
  id,
  campaign_id: "active-1",
  assignee_email: `${id}@example.com`,
  assignee_name: id,
  item_name: "Laptop",
  items: [],
  status,
  assets_returned: false,
});

beforeEach(() => {
  signInWith(["equipment:read", "equipment:write"]);
  server.use(
    http.get("/api/v1/modules/my", () => HttpResponse.json(["equipment"])),
    http.get("/api/v1/equipment/campaigns", () =>
      HttpResponse.json(
        onePage([
          { ...base, id: "draft-1", name: "Draft one", status: "DRAFT" },
          {
            ...base,
            id: "active-1",
            name: "Running one",
            status: "ACTIVE",
            launched_at: "2026-10-01T00:00:00Z",
          },
        ]),
      ),
    ),
    http.get("/api/v1/equipment/campaigns/scope-preview", () =>
      HttpResponse.json({
        assets: 3,
        people: 2,
        without_email: 0,
        holders: ["Anna Nowak", "Piotr Zieliński"],
      }),
    ),
    http.get("/api/v1/equipment/campaigns/active-1", () =>
      HttpResponse.json({
        ...base,
        id: "active-1",
        name: "Running one",
        status: "ACTIVE",
        launched_at: "2026-10-01T00:00:00Z",
        stats: { total: 4, confirmed: 2, disputed: 0, pending: 2, expired: 0 },
        responses: [
          response("a", "CONFIRMED"),
          response("b", "CONFIRMED"),
          response("c", "PENDING"),
          response("d", "PENDING"),
        ],
      }),
    ),
  );
  render(
    <ModulesProvider>
      <PageHeaderContext.Provider value={{ data: {}, setHeader: () => {} }}>
        <AuditCampaignsPage />
      </PageHeaderContext.Provider>
    </ModulesProvider>,
  );
});

afterEach(() => {
  signOut();
});

describe("the attestation list", () => {
  it("names who a draft will ask, before Launch", async () => {
    expect(await screen.findByText(/Anna Nowak/)).toBeInTheDocument();
    expect(screen.getByText(/Piotr Zieliński/)).toBeInTheDocument();
  });

  it("says how many answers are still out when asked to Complete", async () => {
    const user = userEvent.setup();
    await screen.findByText("Running one");
    await user.click(await screen.findByRole("button", { name: /Complete/ }));

    const dialog = await screen.findByRole("alertdialog");
    expect(
      within(dialog).getByText(/2 responses have not been answered/),
    ).toBeInTheDocument();
  });
});
