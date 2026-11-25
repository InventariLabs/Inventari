import { test, expect } from "./fixtures/auth";
import { startSeed } from "./helpers/receive-seed";
import { dayButtonName, isoDay, pickDay } from "./helpers/date-picker";

/**
 * A delivery cost that arrives after the receipt is posted cannot go into the
 * goods: it is recorded as a variance on the receipt, listed with its reason
 * and day, added up on the office list, and never touches the stock value.
 *
 * The form, its mutation and the two lists each have a component test; this
 * walks the wiring between them, and reads the record back through the API.
 */

const DAY_LABEL = "Day it belongs to";

test("a variance recorded on a posted receipt is on its card and on the list, then gone once removed", async ({
  page,
  playwright,
  baseURL,
  authenticatedPage: _auth,
}, testInfo) => {
  const seed = await startSeed({ playwright }, baseURL, testInfo);
  const shelf = await seed.shelf("Shelf");
  const supplier = await seed.partner("Supplier", "SUPPLIER");
  const milk = await seed.product("Milk");
  const receipt = await seed.api.createDocument(seed.token, {
    type: "IN",
    partner_id: supplier.id,
    target_location_id: shelf.id,
    lines: [
      {
        product_template_id: milk.id,
        expected_quantity: 5,
        unit_price: "10.00",
      },
    ],
  });
  await seed.api.confirmDocument(seed.token, receipt.id);
  await seed.api.completeDocument(seed.token, receipt.id);
  // The draft's number is replaced when the receipt is posted.
  const number = (await seed.api.getDocument(seed.token, receipt.id))
    .number as string;

  const variances = async () =>
    (
      (await (
        await seed.request.get(
          `/api/v1/warehouse/documents/${receipt.id}/extra-costs`,
          { headers: { Authorization: `Bearer ${seed.token}` } },
        )
      ).json()) as {
        variances: Array<{ occurred_on: string; amount: string; reason: string }>;
        variance_total: string;
      }
    );

  await page.goto(`/warehouse/documents/${receipt.id}`);
  const section = page
    .getByRole("heading", { name: "Costs that reached no product" })
    .locator("xpath=ancestor::*[contains(@class,'p-4')][1]");
  await expect(section).toBeVisible({ timeout: 15000 });
  const record = section.getByRole("button", { name: "Record as variance" });
  const amount = section.getByRole("textbox", { name: /^Amount/ });
  const reason = section.getByRole("textbox", { name: /^Reason/ });
  const day = section.getByRole("combobox", { name: new RegExp(DAY_LABEL) });

  const todayText = await day.innerText();

  // All three fields the button waits for are marked, and it waits.
  for (const field of [amount, reason, day]) {
    await expect(field).toHaveAttribute("aria-required", "true");
  }
  await expect(record).toBeDisabled();

  // A day after today cannot be picked.
  await day.click();
  const tomorrow = new Date();
  tomorrow.setDate(tomorrow.getDate() + 1);
  await expect(
    page.getByRole("button", { name: dayButtonName(tomorrow) }),
  ).toBeDisabled();
  await page.keyboard.press("Escape");

  // A bill for yesterday's delivery, typed today, is dated yesterday.
  const yesterday = isoDay(-1);
  await amount.fill("40.00");
  await reason.fill(`Freight bill ${seed.uid}`);
  await pickDay(page, day, yesterday);
  await expect(day).not.toHaveText(todayText);
  await record.click();

  await expect(section.getByText(`Freight bill ${seed.uid}`)).toBeVisible();
  await expect(section.getByText(/^Total:/)).toContainText("40.00");
  const stored = await variances();
  expect(stored.variances).toHaveLength(1);
  expect(stored.variances[0].occurred_on).toBe(yesterday);
  expect(Number(stored.variances[0].amount)).toBe(40);
  expect(Number(stored.variance_total)).toBe(40);

  // The form is empty again and the day is back on today.
  await expect(amount).toHaveValue("");
  await expect(reason).toHaveValue("");
  await expect(record).toBeDisabled();
  await expect(day).toHaveText(todayText);

  // The office list carries it, linked to the receipt it belongs to.
  await page.goto("/warehouse/cost-variances");
  const row = page
    .getByRole("row")
    .filter({ hasText: `Freight bill ${seed.uid}` });
  await expect(row).toHaveCount(1, { timeout: 15000 });
  await expect(row).toContainText("40.00");
  await expect(row).toContainText("Freight");
  await row.getByRole("link", { name: number }).click();
  await expect(page).toHaveURL(new RegExp(`/warehouse/documents/${receipt.id}`));

  // Removing it takes it off the card, the list and the record.
  await section
    .getByRole("button", { name: "Remove this variance" })
    .click();
  await expect(section.getByText(`Freight bill ${seed.uid}`)).toHaveCount(0);
  expect((await variances()).variances).toHaveLength(0);
  await page.goto("/warehouse/cost-variances");
  await expect(page.getByText(`Freight bill ${seed.uid}`)).toHaveCount(0);
});
