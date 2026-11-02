import { test, expect } from "./fixtures/auth";
import { ApiHelper } from "./helpers/api";
import { ADMIN_EMAIL, ADMIN_PASSWORD } from "./fixtures/credentials";

/**
 * Paste-from-clipboard import flow.
 * The acceptance criterion from the execution plan: 10 lines imported in ≤ 20 s.
 */

const UID = `${Date.now()}-${Math.floor(Math.random() * 100000)}`;

test.describe("Documents — paste import", () => {
  let api: ApiHelper;
  let token: string;
  let docId: string;

  test.beforeAll(async ({ playwright, baseURL }) => {
    const ctx = await playwright.request.newContext({ baseURL });
    api = new ApiHelper(ctx);
    const auth = await api.login(ADMIN_EMAIL, ADMIN_PASSWORD);
    token = auth.access_token;
    await api.enableAllModules(token);

    const storage = await api.createStorage(token, {
      name: `E2E-Paste-Storage-${UID}`,
    });
    const partner = await api.createPartner(token, {
      name: `E2E-Paste-Partner-${UID}`,
      type: "supplier",
      email: "e2e-paste@example.com",
    });
    const doc = await api.createDocument(token, {
      type: "IN",
      partner_id: partner.id,
      target_location_id: storage.id,
      lines: [{ name: `E2E-Paste-Seed-${UID}`, expected_quantity: 1 }],
    });
    docId = doc.id;
  });

  test.afterAll(async () => {
    if (token && docId) {
      await api.deleteDocument(token, docId).catch(() => {});
    }
  });

  test("imports 10 pasted lines in under 20 seconds", async ({
    page,
    authenticatedPage,
  }) => {
    // The draft's own page offers Edit in its action bar; /warehouse is the
    // History of posted entries and does not list drafts by default.
    await page.goto(`/warehouse/documents/${docId}`);
    await page.getByRole("button", { name: "Edit", exact: true }).click();

    // Open the import sheet from the document form.
    await page
      .getByRole("button", { name: /import lines/i })
      .click({ timeout: 10000 });

    // Switch to the paste tab.
    await page.getByRole("tab", { name: /paste from clipboard/i }).click();

    const lines = Array.from(
      { length: 10 },
      (_, i) => `Paste Widget ${i + 1}\t${i + 1}`,
    );
    const pasted = ["name\tquantity", ...lines].join("\n");

    const startedAt = Date.now();

    await page
      .getByRole("textbox", { name: /paste from clipboard/i })
      .fill(pasted);
    await page.getByRole("button", { name: /^parse$/i }).click();

    // Preview appears with all 10 rows detected.
    await expect(page.getByText("10 rows")).toBeVisible({ timeout: 15000 });

    // Map the columns: Name (first combobox) -> "name", Qty (5th) -> "quantity".
    // Radix Select renders a visible <button role="combobox"> plus a hidden
    // native <select>. The documents list behind the sheet has date filters of
    // the same role, so the mapping selects are scoped to the sheet.
    const sheet = page.getByRole("dialog", { name: /import lines/i });
    const combos = sheet.locator('button[role="combobox"]');
    await combos.nth(0).click();
    await page.getByRole("option", { name: "name", exact: true }).click();
    await combos.nth(4).click();
    await page.getByRole("option", { name: "quantity", exact: true }).click();

    await page.getByRole("button", { name: /^import$/i }).click();

    await expect(page.getByText(/10 lines imported/i)).toBeVisible({
      timeout: 15000,
    });

    const elapsedMs = Date.now() - startedAt;
    expect(elapsedMs).toBeLessThan(20_000);
  });
});
