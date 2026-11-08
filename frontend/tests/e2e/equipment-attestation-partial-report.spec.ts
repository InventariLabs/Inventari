import { test, expect } from "./fixtures/auth";
import { ApiHelper } from "./helpers/api";
import { ADMIN_EMAIL, ADMIN_PASSWORD } from "./fixtures/credentials";

/**
 * One person holds three assets and gets one attestation link. They report
 * one of them as damaged, come back to the same link later and confirm the
 * other two; the campaign page then tells each asset's own story.
 *
 * The seams this crosses — the public page, the response that stays open
 * after a partial report, and the manager's detail naming the reported asset —
 * each have component and backend tests, but no single one sees the whole
 * walk, which is the order a person actually takes it in.
 */

test("a partial report leaves the link open for the rest, and the campaign names the reported asset", async ({
  page,
  playwright,
  baseURL,
  authenticatedPage,
}, testInfo) => {
  void authenticatedPage;
  await page.setViewportSize({ width: 1440, height: 900 });

  const api = new ApiHelper(await playwright.request.newContext({ baseURL }));
  const { access_token: token } = await api.login(ADMIN_EMAIL, ADMIN_PASSWORD);
  const tag = `E2E-Attest-${testInfo.project.name}-${Date.now()}`;
  const cleanup: Array<() => Promise<unknown>> = [];

  try {
    const storage = (await api.listStorages(token))[0];
    const category = await api.createCategoryIdempotent(token, {
      name: tag,
      context_tag: "equipment",
    });
    cleanup.push(() => api.deleteCategory(token, category.id));

    // A category of their own, so the campaign asks about these three assets
    // and about nothing another spec left checked out.
    const holder = `${tag}@example.com`;
    const names = ["Alpha", "Bravo", "Charlie"].map((n) => `${tag} ${n}`);
    const [damaged, ...rest] = names;
    for (const name of names) {
      const item = await api.createEquipmentItem(token, {
        name,
        quantity: 1,
        location_id: storage.id,
        category_id: category.id,
        metadata: { equipment: { equipment_status: "AVAILABLE" } },
      });
      cleanup.push(() => api.deleteItem(token, item.id));
      await api.checkoutAsset(token, {
        item_id: item.id,
        assigned_to_name: "Pat Holder",
        assigned_to_email: holder,
      });
    }

    const campaign = await api.createCampaign(token, {
      name: `${tag} audit`,
      scope_type: "CATEGORY",
      scope_filter_id: category.id,
      deadline: new Date(Date.now() + 7 * 86_400_000).toISOString(),
    });
    cleanup.push(() => api.deleteCampaign(token, campaign.id));
    await api.launchCampaign(token, campaign.id);

    const { responses } = await api.getCampaign(token, campaign.id);
    expect(responses).toHaveLength(1);
    const link = await api.campaignResponseLink(
      token,
      campaign.id,
      responses[0].id,
    );
    const publicPath = new URL(link).pathname;

    // ── First visit: report one of the three ───────────────────────────
    await page.goto(publicPath);
    for (const name of names) {
      await expect(page.getByText(name, { exact: false })).toBeVisible();
    }
    await page.getByRole("button", { name: "Report Issue" }).click();
    await page.getByRole("combobox", { name: /select the asset/i }).click();
    await page.getByRole("option", { name: new RegExp(damaged) }).click();
    await page.getByRole("combobox", { name: /issue type/i }).click();
    await page.getByRole("option", { name: /^damaged/i }).click();
    await page.getByLabel("Details").fill("Cracked casing");
    await page.getByRole("button", { name: "Submit Report" }).click();

    // The report does not settle the response: the other two still wait.
    const stillOpen = page.getByText(
      /assets you have not answered for are still waiting/i,
    );
    await expect(stillOpen).toBeVisible();
    await expect(
      page.getByRole("heading", { name: "Issue Reported" }),
    ).toHaveCount(0);

    // ── The link, opened again ─────────────────────────────────────────
    await page.reload();
    await expect(stillOpen).toBeVisible();
    await expect(
      page.getByRole("heading", { name: "Issue Reported" }),
    ).toHaveCount(0);
    await expect(
      page.getByRole("listitem").filter({ hasText: damaged }),
    ).toContainText(/reported/i);
    for (const name of rest) {
      const row = page.getByRole("listitem").filter({ hasText: name });
      await expect(row).toBeVisible();
      await expect(row).not.toContainText(/reported|confirmed/i);
    }

    // ── Confirm what is left ───────────────────────────────────────────
    await page.getByRole("button", { name: "I have these assets" }).click();
    await page.getByRole("button", { name: "Yes, I have them" }).click();
    await expect(
      page.getByRole("heading", { name: "Issue Reported" }),
    ).toBeVisible();
    await expect(
      page.getByText(/confirmation of 2 other assets/i),
    ).toBeVisible();

    // ── The manager's page: each asset's own status, the report by name ─
    await page.goto(`/equipment/campaigns/${campaign.id}`);
    const table = page.getByRole("table");
    for (const name of rest) {
      await expect(
        table.getByRole("listitem").filter({ hasText: name }).first(),
      ).toContainText("(Confirmed)");
    }
    await expect(
      table.getByRole("listitem").filter({ hasText: damaged }).first(),
    ).toContainText("(Disputed)");
    const note = table.getByRole("cell").last();
    await expect(note).toContainText(damaged);
    await expect(note).toContainText("Damaged");
    await expect(note).toContainText("Cracked casing");
  } finally {
    for (const undo of cleanup.reverse()) await undo().catch(() => {});
  }
});
