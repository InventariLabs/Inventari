import { randomUUID } from "node:crypto";

import { type APIRequestContext } from "@playwright/test";
import { test, expect } from "./fixtures/auth";
import { ApiHelper } from "./helpers/api";
import { ADMIN_EMAIL, ADMIN_PASSWORD } from "./fixtures/credentials";

/**
 * The header action "Send for approval" on a draft receipt opens a one-step
 * dialog. The server answers, before the click, whether the workflow has a
 * stage nobody could decide; the dialog has to say so, or a correct answer
 * from the requirement endpoint hides behind a generic promise of "the
 * approval queue".
 *
 * Two stages: the first is open to anyone holding the approve permission
 * (the admin may decide it, self-approval being on), the second names a
 * member who cannot see approvals at all. The workflow and the profile are
 * organisation-wide, so the file belongs to the `approvals` project, which
 * runs alone; both are put back in `afterAll`.
 */

type Profile = Record<string, unknown>;

const UID = randomUUID().slice(0, 8);
const BLIND_PASSWORD = "Blind-Member-9x!";

test.describe("Send for approval — dead end at a later stage", () => {
  test.describe.configure({ mode: "serial" });

  let ctx: APIRequestContext;
  let api: ApiHelper;
  let token: string;
  let original: Profile;
  let workflowId: string;
  let blindId: string;
  let draftId: string;

  const auth = () => ({ Authorization: `Bearer ${token}` });

  async function readProfile(): Promise<Profile> {
    const response = await ctx.get("/api/v1/warehouse/profile", {
      headers: auth(),
    });
    expect(response.ok(), await response.text()).toBe(true);
    return (await response.json()) as Profile;
  }

  async function writeProfile(changes: Profile): Promise<void> {
    const current = await readProfile();
    const body = Object.fromEntries(
      Object.entries({ ...current, ...changes }).filter(
        ([key]) =>
          !["id", "organization_id", "created_at", "updated_at"].includes(key),
      ),
    );
    const response = await ctx.put("/api/v1/warehouse/profile", {
      headers: auth(),
      data: body,
    });
    expect(response.ok(), await response.text()).toBe(true);
  }

  /** Replace what the second stage names, keeping the workflow switched on. */
  async function nameSecondStage(approvers: string[]): Promise<void> {
    const stages = [
      {
        order: 1,
        role: "manager",
        label: "Team lead",
        approver_user_ids: [],
      },
      {
        order: 2,
        role: "director",
        label: "Director",
        approver_user_ids: approvers,
      },
    ];
    if (!workflowId) {
      // Saved off, then switched on: the scope it will hold is readable only
      // from the list.
      const created = await api.createWorkflow(token, {
        target_type: "document",
        name: `E2E-DeadEnd-${UID}`,
        stages,
        allow_undecidable_stages: true,
      });
      workflowId = created.id;
    } else {
      await api.updateWorkflow(token, workflowId, {
        stages,
        allow_undecidable_stages: true,
      });
    }
    const listed = await ctx.get("/api/v1/approvals/workflows", {
      headers: auth(),
    });
    const row = (await listed.json()).items.find(
      (w: { id: string }) => w.id === workflowId,
    );
    await api.updateWorkflow(token, workflowId, {
      is_active: true,
      expected_scope: row?.scope ?? null,
      allow_undecidable_stages: true,
    });
  }

  test.beforeAll(async ({ playwright, baseURL }) => {
    ctx = await playwright.request.newContext({ baseURL });
    api = new ApiHelper(ctx);
    token = (await api.login(ADMIN_EMAIL, ADMIN_PASSWORD)).access_token;
    await api.enableAllModules(token);
    await api.setModuleSettings(token, "approvals", {
      allow_admin_self_approve: true,
    });
    original = await readProfile();

    // A member who holds no role beyond the default: the stage can name
    // them, and they still cannot see approvals.
    const email = `deadend-e2e-${UID}@example.com`;
    const { invite_code } = await api.createInvite(token, email);
    const registered = await ctx.post("/api/v1/auth/register", {
      data: { email, password: BLIND_PASSWORD, invite_code },
    });
    expect(registered.ok(), await registered.text()).toBe(true);
    const blind = await api.login(email, BLIND_PASSWORD);
    const me = await ctx.get("/api/v1/auth/me", {
      headers: { Authorization: `Bearer ${blind.access_token}` },
    });
    blindId = (await me.json()).id;

    const storage = await api.createStorage(token, {
      name: `E2E-DeadEnd-WH-${UID}`,
    });
    const partner = await api.createPartner(token, {
      name: `E2E-DeadEnd-Supplier-${UID}`,
      type: "supplier",
      email: "e2e-deadend@example.com",
    });
    const draft = await api.createDocument(token, {
      type: "IN",
      partner_id: partner.id,
      target_location_id: storage.id,
      lines: [{ name: `E2E-DeadEnd-Line-${UID}`, expected_quantity: 1 }],
    });
    draftId = draft.id;
    await writeProfile({ approval_required_for_types: ["IN"] });
  });

  test.afterAll(async () => {
    if (workflowId) await api.deleteWorkflow(token, workflowId);
    await writeProfile({
      approval_required_for_types: original.approval_required_for_types,
    });
    if (draftId) await api.deleteDocument(token, draftId).catch(() => {});
    if (blindId) {
      await ctx
        .post(`/api/v1/organizations/my/remove-member/${blindId}`, {
          headers: auth(),
        })
        .catch(() => {});
    }
    await ctx.dispose();
  });

  test("the dialog names the stage nobody can decide, and the plain one returns once it can be decided", async ({
    page,
    authenticatedPage,
  }) => {
    void authenticatedPage;

    // The requirement endpoint is right: the Director stage cannot be decided.
    await nameSecondStage([blindId]);
    const told = await ctx.get(
      `/api/v1/approvals/documents/${draftId}/approval-requirement`,
      { headers: auth() },
    );
    expect(told.ok(), await told.text()).toBe(true);
    const verdict = await told.json();
    expect(verdict.approval_solvable).toBe(false);
    expect(verdict.undecidable_stage).toBe("Director");

    // The header action itself, not the endpoint, is what the reader sees.
    await page.goto(`/warehouse/documents/${draftId}`);
    await page
      .getByRole("button", { name: "Send for approval", exact: true })
      .click();
    const dialog = page.getByRole("alertdialog");
    await expect(dialog).toBeVisible({ timeout: 15000 });
    await expect(dialog).toContainText("nobody could decide it");
    await expect(dialog).toContainText("“Director”");
    await expect(dialog).toContainText("those people are given access");
    await expect(dialog).not.toContainText("Once approved, it is posted");
    await dialog.getByRole("button", { name: "Keep as draft" }).click();
    await expect(dialog).toBeHidden();

    // Open the Director stage to anyone holding the grant: the admin holds
    // it, every stage can be decided, and the ordinary sentence is back.
    await nameSecondStage([]);
    await page.reload();
    await page
      .getByRole("button", { name: "Send for approval", exact: true })
      .click();
    await expect(dialog).toBeVisible({ timeout: 15000 });
    await expect(dialog).toContainText("Once approved, it is posted");
    await expect(dialog).not.toContainText("nobody could decide");
  });
});
