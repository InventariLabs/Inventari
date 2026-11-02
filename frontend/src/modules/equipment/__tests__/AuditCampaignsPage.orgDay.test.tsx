import { describe, expect, it, afterEach } from "vitest";
import { render, screen } from "@/test/utils";
import { server } from "@/test/mocks/server";
import { http, HttpResponse } from "msw";
import { PageHeaderContext } from "@/hooks/useModulePageHeader";
import AuditCampaignsPage from "../pages/AuditCampaignsPage";
import { onePage } from "@/test/mocks/page";

/**
 * The deadline reproduction on the screen itself.
 *
 * The campaign was created with deadline "the 25th" for an organization
 * whose clock is America/New_York; the stored instant is the end of that
 * org day. A reader in Europe/Warsaw (two hours east of UTC, New York four
 * west) used to see "09/26/2026" on this list — the browser's zone reading
 * a value pinned to another clock. With the organization's timezone mocked,
 * the card must name the org's day.
 */

const deadline = "2026-09-26T03:59:59.999999Z"; // 23:59:59.999999 in New York

const campaign = {
  id: "campaign-1",
  organization_id: "org-1",
  name: "Kitchen audit",
  description: null,
  scope_type: "ALL",
  scope_filter_id: null,
  launched_at: null,
  deadline,
  reminder_days_before: 3,
  last_reminder_sent_at: null,
  status: "DRAFT",
  email_subject: null,
  email_body: null,
  created_by: "user-1",
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};

function inZone(zone: string, body: () => Promise<void> | void): Promise<void> {
  const original = process.env.TZ;
  process.env.TZ = zone;
  return Promise.resolve()
    .then(body)
    .finally(() => {
      process.env.TZ = original;
    });
}

afterEach(() => {
  process.env.TZ = undefined;
});

describe("AuditCampaignsPage — the deadline reads the organization's clock", () => {
  it("a Warsaw reader sees the New York day the org picked, not the next one", async () => {
    await inZone("Europe/Warsaw", async () => {
      server.use(
        http.get("/api/v1/equipment/campaigns", () =>
          HttpResponse.json(onePage([campaign])),
        ),
        http.get("/api/v1/organizations/my", () =>
          HttpResponse.json({ timezone: "America/New_York" }),
        ),
      );

      render(
        <PageHeaderContext.Provider value={{ data: {}, setHeader: () => {} }}>
          <AuditCampaignsPage />
        </PageHeaderContext.Provider>,
      );

      await screen.findByText("Kitchen audit");
      expect(screen.getByText(/Deadline: Sep 25, 2026/)).toBeInTheDocument();
      expect(screen.queryByText(/Sep 26, 2026/)).not.toBeInTheDocument();
    });
  });
});
