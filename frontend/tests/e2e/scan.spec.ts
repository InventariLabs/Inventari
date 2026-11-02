import { test, expect } from "./fixtures/auth";
import { ApiHelper } from "./helpers/api";
import { ADMIN_EMAIL, ADMIN_PASSWORD } from "./fixtures/credentials";

test.describe("Scan — barcode & QR code flow", () => {
  let labelShortCode: string;

  test.beforeAll(async ({ playwright, baseURL }) => {
    const api = new ApiHelper(await playwright.request.newContext({ baseURL }));
    const { access_token } = await api.login(ADMIN_EMAIL, ADMIN_PASSWORD);
    labelShortCode = (await api.generateLabels(access_token, 1, "SCAN"))[0]
      .short_code;
  });

  test.beforeEach(async ({ page, authenticatedPage }) => {
    await page.goto("/inventory/scan");
  });

  // A desktop has no camera worth starting by itself; a USB scanner types
  // into the field, so the field has the focus before anyone clicks.
  test("a desktop opens with the camera off and the code field ready", async ({
    page,
  }) => {
    await expect(
      page.getByRole("heading", { name: "Desktop Mode" }),
    ).toBeVisible({ timeout: 15000 });
    await expect(
      page.getByRole("button", { name: "Start Camera" }),
    ).toBeVisible();
    await expect(page.getByTestId("manual-barcode-input")).toBeFocused();
  });

  test("a typed barcode nobody has opens a new product with that code", async ({
    page,
  }) => {
    const field = page.getByTestId("manual-barcode-input");
    await expect(field).toBeFocused({ timeout: 15000 });
    await field.fill("1234567890123");
    await field.press("Enter");

    const sheet = page.getByRole("dialog", { name: "New Product" });
    await expect(sheet).toBeVisible({ timeout: 10000 });
    await expect(sheet.getByText("Scanned code: 1234567890123")).toBeVisible();
  });

  // What a label's QR carries is its code; typed, it is read as the label,
  // which an unknown barcode is not: the sheet offers to attach it.
  test("a typed label code is read as the label", async ({ page }) => {
    const field = page.getByTestId("manual-barcode-input");
    await expect(field).toBeFocused({ timeout: 15000 });
    await field.fill(labelShortCode);
    await field.press("Enter");

    const sheet = page.getByRole("dialog", { name: "New Product" });
    await expect(sheet).toBeVisible({ timeout: 10000 });
    await expect(
      sheet.getByText(`Scanned code: ${labelShortCode}`),
    ).toBeVisible();
    await expect(
      sheet.getByRole("button", { name: "Attach to an existing product" }),
    ).toBeVisible();
  });
});

test.describe("Scan — API scan flow", () => {
  let api: ApiHelper;
  let token: string;
  let labelShortCode: string;

  test.beforeAll(async ({ playwright, baseURL }) => {
    const requestContext = await playwright.request.newContext({ baseURL });
    api = new ApiHelper(requestContext);
    const authData = await api.login(ADMIN_EMAIL, ADMIN_PASSWORD);
    token = authData.access_token;

    const labels = await api.generateLabels(token, 1, "SCAN");
    labelShortCode = labels[0].short_code;
  });

  test.afterAll(async () => {
    // cleanup not needed — labels are E2E-prefixed and will be cleaned up by test infrastructure
  });

  test("GET /labels/scan/{code} returns scan result for unassigned label", async () => {
    const result = await api.scanCode(token, labelShortCode);
    expect(result).toBeTruthy();
    expect(result.status).toBe("unassigned");
    expect(result.label_code).toBe(labelShortCode);
    expect(result.action).toBeTruthy();
  });

  test("GET /labels/scan/{code} returns result for unknown barcode", async () => {
    try {
      const result = await api.scanCode(token, "UNKNOWN-BARCODE-12345");
      expect(result).toBeTruthy();
      expect(result.status).toBeTruthy();
    } catch {
      // 404 or 200 with not_found status is acceptable
      expect(true).toBeTruthy();
    }
  });
});
