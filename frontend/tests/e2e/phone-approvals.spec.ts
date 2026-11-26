import type { Locator, Page } from "@playwright/test";
import { expect, test } from "./fixtures/auth";
import { ApiHelper } from "./helpers/api";
import { ADMIN_EMAIL, ADMIN_PASSWORD } from "./fixtures/credentials";
import {
  PHONE_HEIGHT,
  PHONE_WIDTH,
  expectFirstRecordAboveFold,
} from "./helpers/phone-first-record";

/**
 * The approval lists on a phone: the first record is above the fold.
 *
 * `phone-first-record-responsive.spec.ts` measures every other list. These need
 * an approval workflow, and a workflow holds every document of the
 * organization while it exists, so they run in the `approvals-mobile` project, alone,
 * as the other approval specs do. The workflow and the request they measure
 * are seeded here, so the record is always there.
 */
test.describe("Phone approval lists — the first record is above the fold", () => {
  let api: ApiHelper;
  let token: string;
  let tag: string;
  const cleanup: (() => Promise<unknown>)[] = [];

  test.beforeAll(async ({ playwright, baseURL }) => {
    cleanup.length = 0;
    const requestContext = await playwright.request.newContext({ baseURL });
    api = new ApiHelper(requestContext);
    token = (await api.login(ADMIN_EMAIL, ADMIN_PASSWORD)).access_token;
    await api.enableAllModules(token);
    await api.cleanupApprovals(token);

    tag = `PhoneApprovals-${Date.now()}`;
    const from = await api.createStorage(token, { name: `${tag} place` });
    cleanup.push(() => api.deleteStorage(token, from.id));
    const to = await api.createStorage(token, { name: `${tag} shelf` });
    cleanup.push(() => api.deleteStorage(token, to.id));

    const workflow = await api.createWorkflow(token, {
      target_type: "document",
      is_active: true,
      name: `${tag} workflow`,
      stages: [
        { order: 1, label: "Review", role: "manager", approver_user_ids: [] },
      ],
    });
    cleanup.push(() => api.deleteWorkflow(token, workflow.id));

    const document = await api.createIntDocumentWithStock(token, {
      source_location_id: from.id,
      target_location_id: to.id,
      lines: [{ name: `${tag} transfer`, expected_quantity: 1 }],
    });
    cleanup.push(() => api.deleteDocument(token, document.id));
    // With the workflow in force, confirming the document opens its request.
    await api.confirmDocument(token, document.id);
  });

  test.afterAll(async () => {
    // Last created, first removed: the workflow goes before what it held.
    for (const undo of cleanup.reverse()) await undo().catch(() => {});
  });

  test.beforeEach(async ({ page, authenticatedPage }) => {
    await page.setViewportSize({ width: PHONE_WIDTH, height: PHONE_HEIGHT });
  });

  const ROUTES: {
    name: string;
    path: string;
    record: (page: Page) => Locator;
  }[] = [
    {
      name: "approvals",
      path: "/approvals",
      record: (page) => page.locator("[data-testid=approval-card]").first(),
    },
    {
      name: "warehouse approvals",
      path: "/warehouse/approvals",
      record: (page) => page.getByText(/^[A-Z]+\/\d{4}(?:\/\d{2})?\/\d+$/).first(),
    },
    {
      name: "approval workflows",
      path: "/approvals/workflows",
      record: (page) => page.getByText(`${tag} workflow`).first(),
    },
  ];

  for (const route of ROUTES) {
    test(`${route.name}: the first record starts above the fold`, async ({
      page,
    }) => {
      await page.goto(route.path);
      await expectFirstRecordAboveFold(route.path, route.record(page));
    });
  }
});

test.describe("Phone equipment issue — the approval refusal is in view", () => {
  let api: ApiHelper;
  let token: string;
  const cleanup: (() => Promise<unknown>)[] = [];
  let assetId = "";

  test.beforeAll(async ({ playwright, baseURL }) => {
    cleanup.length = 0;
    const requestContext = await playwright.request.newContext({ baseURL });
    api = new ApiHelper(requestContext);
    token = (await api.login(ADMIN_EMAIL, ADMIN_PASSWORD)).access_token;
    await api.enableAllModules(token);
    await api.cleanupApprovals(token);

    const tag = `PhoneIssue-${Date.now()}`;
    const place = await api.createStorage(token, { name: `${tag} place` });
    cleanup.push(() => api.deleteStorage(token, place.id));
    assetId = (
      await api.createEquipmentItem(token, {
        name: `${tag} laptop`,
        quantity: 1,
        location_id: place.id,
      })
    ).id;
    cleanup.push(() => api.deleteItem(token, assetId));
    const workflow = await api.createWorkflow(token, {
      target_type: "equipment_checkout",
      is_active: true,
      name: `${tag} workflow`,
      stages: [
        { order: 1, label: "Review", role: "manager", approver_user_ids: [] },
      ],
    });
    cleanup.push(() => api.deleteWorkflow(token, workflow.id));
  });

  test.afterAll(async () => {
    for (const undo of cleanup.reverse()) await undo().catch(() => {});
  });

  test("shows the refusal and the way to ask, on the screen", async ({
    page,
    authenticatedPage,
  }) => {
    await page.setViewportSize({ width: PHONE_WIDTH, height: PHONE_HEIGHT });
    await page.goto(`/equipment/${assetId}`);
    await page.getByRole("button", { name: /^check out$/i }).first().click();
    const sheet = page.getByTestId("checkout-modal-card");
    await sheet.getByPlaceholder(/john smith/i).fill("Phone Holder");
    await sheet.getByRole("button", { name: /^check out$/i }).click();

    await expect(
      sheet.getByRole("button", {
        name: "Request approval for this checkout",
      }),
    ).toBeInViewport();
  });
});
