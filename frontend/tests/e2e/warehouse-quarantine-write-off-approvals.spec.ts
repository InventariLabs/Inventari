import type { Locator, Page } from "@playwright/test";
import { test, expect } from "./fixtures/auth";
import { startSeed, type ReceivingSeed } from "./helpers/receive-seed";
import {
  HELD,
  receiveWithDamagedGoods,
  type HeldGoods,
} from "./helpers/quarantine-hold";

/**
 * Goods held in quarantine without a batch are written off from the Start
 * screen's quarantine block in one step. Two outcomes are read back through
 * the ledger and the document, not the toast:
 *
 * - posted at once: the damaged goods leave the quarantine shelf and the
 *   stock on the shelf next to it stays as it was;
 * - when scrapping needs a manager's signature: the document is parked, the
 *   screen says it was sent for approval instead of claiming the goods are
 *   gone, and the quarantine shelf still holds them.
 *
 * Receiving names the organisation's quarantine location and the second case
 * switches on an approval workflow, both organisation-wide, so this file is
 * named for the `approvals` project, which runs alone and in one worker after
 * the rest. The profile and the workflow are put back at the end.
 */
test.use({ viewport: { width: 1280, height: 800 } });
test.describe.configure({ mode: "serial" });

const PROFILE = "/api/v1/warehouse/profile";
const SERVER_FIELDS = ["id", "organization_id", "created_at", "updated_at"];

let seed: ReceivingSeed;
let original: Record<string, unknown>;
const workflows: string[] = [];
const parked: string[] = [];

const headers = () => ({ Authorization: `Bearer ${seed.token}` });

/** The profile is replaced whole; change only the fields named. */
async function writeProfile(changes: Record<string, unknown>): Promise<void> {
  const current = await (
    await seed.request.get(PROFILE, { headers: headers() })
  ).json();
  const body = Object.fromEntries(
    Object.entries({ ...current, ...changes }).filter(
      ([key]) => !SERVER_FIELDS.includes(key),
    ),
  );
  const put = await seed.request.put(PROFILE, {
    headers: headers(),
    data: body,
  });
  expect(put.ok(), await put.text()).toBe(true);
}

/** The hold's row in the quarantine block, found by its product's name. */
function holdRow(page: Page, held: HeldGoods): Locator {
  return page
    .getByRole("region", { name: "Quarantine holds" })
    .locator("div.rounded-xl, [class*=card]")
    .filter({ hasText: held.product.name })
    .filter({ has: page.getByRole("button", { name: "Write off" }) })
    .last();
}

test.beforeAll(async ({ playwright, baseURL }, testInfo) => {
  seed = await startSeed({ playwright }, baseURL, testInfo);
  original = await (
    await seed.request.get(PROFILE, { headers: headers() })
  ).json();
});

// A seed of its own per test: its names carry a stamp, and a second test on
// the first one's stamp would meet the first one's supplier.
test.beforeEach(async ({ playwright, baseURL }, testInfo) => {
  seed = await startSeed({ playwright }, baseURL, testInfo);
});

test.afterAll(async () => {
  for (const id of parked) await seed.api.cancelDocument(seed.token, id);
  for (const id of workflows) await seed.api.deleteWorkflow(seed.token, id);
  await writeProfile({
    approval_required_for_types: original.approval_required_for_types,
    quarantine_location_id: original.quarantine_location_id,
  });
});

test("a quarantine hold is written off from Start and leaves the shelf", async ({
  page,
  authenticatedPage: _auth,
}) => {
  const held = await receiveWithDamagedGoods(page, seed);

  await page.goto("/warehouse/todo");
  const row = holdRow(page, held);
  await expect(row).toBeVisible({ timeout: 15000 });
  await expect(row).toContainText(held.receiptNumber);
  await row.getByRole("button", { name: "Write off" }).click();

  // No reason is chosen for the reader: the button waits for one.
  const dialog = page.getByRole("dialog", {
    name: new RegExp(`Write off: ${held.product.name}`),
  });
  await dialog.getByRole("button", { name: "Write off" }).click();
  await expect(dialog.getByRole("alert")).toHaveText("Pick a reason");
  expect(await seed.onHand(held.product, held.quarantine)).toBe(HELD);

  await dialog
    .getByTestId("hold-write-off-reason-code")
    .selectOption("DAMAGED");
  await dialog.getByRole("button", { name: "Write off" }).click();
  await expect(
    page.getByText(new RegExp(`Wrote off .* of ${held.product.name}`)),
  ).toBeVisible({ timeout: 15000 });

  // The ledger: the held goods are gone, the shelf's stock is untouched.
  await expect
    .poll(() => seed.onHand(held.product, held.quarantine), { timeout: 15000 })
    .toBe(0);
  expect(await seed.onHand(held.product, held.shelf)).toBe(18);

  // The hold no longer waits on Start.
  await expect(
    page
      .getByRole("region", { name: "Quarantine holds" })
      .getByText(held.product.name, { exact: false }),
  ).toHaveCount(0);
});

test("an approval parks the write-off and claims no stock moved", async ({
  page,
  authenticatedPage: _auth,
}) => {
  // The goods are received first: with the workflow in force the receipt
  // itself would wait for a signature and hold nothing.
  const held = await receiveWithDamagedGoods(page, seed);

  const workflow = await seed.api.createWorkflow(seed.token, {
    target_type: "document",
    is_active: true,
    name: `E2E-QuarantineWriteOff-Approval-${Date.now().toString(36)}`,
    stages: [
      {
        order: 1,
        role: "manager",
        label: "Manager approval",
        approver_user_ids: [],
      },
    ],
  });
  workflows.push(workflow.id);
  await writeProfile({ approval_required_for_types: ["SCRAP"] });

  await page.goto("/warehouse/todo");
  const row = holdRow(page, held);
  await expect(row).toBeVisible({ timeout: 15000 });
  await row.getByRole("button", { name: "Write off" }).click();

  const dialog = page.getByRole("dialog", {
    name: new RegExp(`Write off: ${held.product.name}`),
  });
  await dialog
    .getByTestId("hold-write-off-reason-code")
    .selectOption("DAMAGED");
  const posted = page.waitForResponse(
    (r) =>
      r.url().includes("/api/v1/warehouse/documents/post") &&
      r.request().method() === "POST",
  );
  await dialog.getByRole("button", { name: "Write off" }).click();
  const document = (await (await posted).json()) as {
    id: string;
    status: string;
  };
  parked.push(document.id);

  // Parked, and said so: not "Wrote off".
  expect(document.status).toBe("PENDING_APPROVAL");
  await expect(page.getByText("Document sent for approval")).toBeVisible({
    timeout: 15000,
  });
  await expect(page.getByText(/^Wrote off /)).toHaveCount(0);

  // Nothing left the shelf, and the hold still waits on Start.
  expect(await seed.onHand(held.product, held.quarantine)).toBe(HELD);
  await page.reload();
  await expect(holdRow(page, held)).toBeVisible({ timeout: 15000 });
});
