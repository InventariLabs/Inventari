import { test, expect } from "./fixtures/auth";
import { ApiHelper } from "./helpers/api";
import { pickDay } from "./helpers/date-picker";
import { ADMIN_EMAIL, ADMIN_PASSWORD } from "./fixtures/credentials";

/**
 * The rentals flows step 1 shipped without a browser spec: a booking with an
 * "any unit" line made on the sheet (a line that does not fit and both ways
 * out), its hand-out by scan at phone width, and its return with "needs
 * service" that moves a later booking.
 */

const RENTALS = "/api/v1/rentals";

function daysFromNow(days: number, hour = 9): Date {
  const value = new Date();
  value.setUTCDate(value.getUTCDate() + days);
  value.setUTCHours(hour, 0, 0, 0);
  return value;
}

function dateInput(value: Date): string {
  return value.toISOString().slice(0, 10);
}

function at(value: Date): string {
  return value.toISOString();
}

test.describe("Rentals — booking sheet, phone hand-out and a service return", () => {
  test.describe.configure({ mode: "serial" });

  let api: ApiHelper;
  let token: string;
  let categoryId = "";
  let storageId = "";
  let model = "";
  const items: string[] = [];
  const serials: string[] = [];

  test.beforeAll(async ({ playwright, baseURL }, workerInfo) => {
    const requestContext = await playwright.request.newContext({ baseURL });
    api = new ApiHelper(requestContext);
    token = (await api.login(ADMIN_EMAIL, ADMIN_PASSWORD)).access_token;
    const unique = `${workerInfo.project.name}-${Date.now().toString(36)}${Math.random()
      .toString(36)
      .slice(2, 6)}`;
    model = `Rentals E2E Projector ${unique}`;

    const storages = await api.listStorages(token);
    storageId = process.env.E2E_STORAGE_ID || storages[0]?.id || "";
    const category = await api.createCategoryIdempotent(token, {
      name: `E2E-Rentals-${unique}`,
      context_tag: "equipment",
    });
    categoryId = category.id;
    // The model of an asset is its product template, not a free-text field;
    // one template and three records of it is one fleet of three units.
    const template = await api.createProductTemplate(token, { name: model });

    for (let index = 1; index <= 3; index += 1) {
      const item = await api.createEquipmentItem(token, {
        name: `${model} #${index}`,
        template_id: template.id,
        quantity: 1,
        location_id: storageId,
        category_id: categoryId,
        metadata: {
          equipment: {
            serial_number: `RENT-${unique}-${index}`,
            equipment_status: "AVAILABLE",
          },
        },
      });
      items.push(item.id);
      serials.push(`RENT-${unique}-${index}`);
    }
  });

  test.afterAll(async () => {
    for (const id of items) {
      await api.deleteItem(token, id).catch(() => {});
    }
  });

  test("an any-unit line that does not fit offers fewer units and the nearest window", async ({
    page,
    authenticatedPage,
  }) => {
    void authenticatedPage;
    // The sheet opens on tomorrow 09:00 through the day after tomorrow at
    // 16:00. Two of the three units are already promised for that window.
    const starts = daysFromNow(1, 9);
    const ends = daysFromNow(3, 16);
    await api.createRentalBooking(token, {
      starts_at: at(starts),
      ends_at: at(ends),
      borrower_name: "Existing booking",
      lines: [{ model, quantity: 2 }],
    });

    const borrower = `E2E Sheet Borrower ${Date.now().toString(36)}`;
    await page.goto("/rentals/bookings/new");
    await expect(
      page.getByRole("heading", { name: "New booking" }).first(),
    ).toBeVisible();

    await page
      .getByRole("button", { name: "Someone outside the system" })
      .click();
    await page.getByLabel(/^Name/).fill(borrower);
    await page.getByLabel("E-mail").fill("sheet-borrower@example.com");
    await page
      .getByRole("combobox", { name: "Model" })
      .selectOption({ value: model });

    const pickupDate = page.getByLabel("Pickup: date");
    await page.getByRole("button", { name: "More" }).click();
    // Three units, two promised: only one is free for a two-unit line.
    await expect(page.getByText(/Only 1 of 2 are free/)).toBeVisible({
      timeout: 15000,
    });
    const reduce = page.getByRole("button", { name: /Reduce to 1 unit/ });
    const move = page.getByRole("button", {
      name: /Move to .*when enough are free/,
    });
    await expect(reduce).toBeVisible();
    await expect(move).toBeVisible();

    // The first way out: fewer units.
    await reduce.click();
    await expect(page.getByRole("button", { name: "Book" })).toBeEnabled({
      timeout: 15000,
    });

    // The second way out: the nearest window of the same length. Asking for
    // two again brings the conflict back, and the move keeps the count.
    await page.getByRole("button", { name: "More" }).click();
    await expect(move).toBeVisible({ timeout: 15000 });
    const before = await pickupDate.textContent();
    await move.click();
    await expect(pickupDate).not.toHaveText(before ?? "");
    await expect(page.getByRole("button", { name: "Book" })).toBeEnabled({
      timeout: 15000,
    });
    await page.getByRole("button", { name: "Book" }).click();
    await expect(page).toHaveURL(/\/rentals$/);

    const listed = await api.listRentalBookings(
      token,
      `search=${encodeURIComponent(borrower)}&limit=5`,
    );
    expect(listed.total).toBe(1);
    const saved = await api.getRentalBooking(
      token,
      String(listed.items[0].id),
    );
    const lines = saved.lines as Array<{ model: string; quantity: number }>;
    // The move was not a way out by itself: the line still asks for two.
    expect(lines[0]).toMatchObject({ model, quantity: 2 });
  });

  test("a phone scan hands the booking out", async ({
    page,
    authenticatedPage,
  }, workerInfo) => {
    void authenticatedPage;
    const starts = daysFromNow(25);
    const ends = daysFromNow(27, 16);
    const booking = await api.createRentalBooking(token, {
      starts_at: at(starts),
      ends_at: at(ends),
      borrower_name: `E2E Phone Borrower ${workerInfo.project.name}`,
      lines: [{ model, quantity: 1 }],
    });
    const bookingId = String(booking.id);

    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto(`/rentals/bookings/${bookingId}/pickup`);

    // Scanning the unit's serial fills the "any unit" line.
    await page.getByRole("textbox", { name: "Scan" }).fill(serials[2]);
    await page.getByRole("button", { name: "Scan" }).click();
    await expect(page.getByText(/assigned|scanned/)).toBeVisible({ timeout: 10000 });

    const confirm = page.getByRole("button", { name: "Confirm the hand-out" });
    await expect(confirm).toBeEnabled({ timeout: 10000 });
    await confirm.click();
    await expect(page).toHaveURL(
      new RegExp(`/rentals/bookings/${bookingId}$`),
    );
    await expect(page.getByText("Handed out").first()).toBeVisible();

    const stored = await api.getRentalBooking(token, bookingId);
    expect(stored.status).toBe("PICKED_UP");
  });

  test("a return that needs service moves the later booking", async ({
    page,
    authenticatedPage,
  }, workerInfo) => {
    void authenticatedPage;
    const unique = `${workerInfo.project.name}-${Date.now().toString(36)}`;
    // A model of its own: the earlier tests hold units from now on, and a
    // specific-unit return here must not be judged against their promises.
    const returnModel = `${model}-return`;
    const template = await api.createProductTemplate(token, {
      name: returnModel,
    });
    const returnUnits: string[] = [];
    for (let index = 1; index <= 2; index += 1) {
      const item = await api.createEquipmentItem(token, {
        name: `${returnModel} #${index}`,
        template_id: template.id,
        quantity: 1,
        location_id: storageId,
        category_id: categoryId,
        metadata: { equipment: { equipment_status: "AVAILABLE" } },
      });
      returnUnits.push(item.id);
      items.push(item.id);
    }

    const returning = await api.createRentalBooking(token, {
      starts_at: at(daysFromNow(10)),
      ends_at: at(daysFromNow(12, 16)),
      borrower_name: `E2E Returning ${unique}`,
      lines: [{ item_id: returnUnits[0], quantity: 1 }],
    });
    const returningId = String(returning.id);
    await api.pickupRentalBooking(token, returningId, {
      item_ids: [returnUnits[0]],
    });

    const later = await api.createRentalBooking(token, {
      starts_at: at(daysFromNow(14)),
      ends_at: at(daysFromNow(16, 16)),
      borrower_name: `E2E Later ${unique}`,
      lines: [{ item_id: returnUnits[0], quantity: 1 }],
    });
    const laterId = String(later.id);

    await page.goto(`/rentals/bookings/${returningId}`);
    await expect(
      page.getByRole("heading", { name: "Return", exact: true }),
    ).toBeVisible();
    await page.getByRole("button", { name: "Needs service" }).click();
    await page.getByLabel("What happened").fill("Lens cracked");
    await pickDay(
      page,
      page.getByLabel("Unavailable until: date"),
      dateInput(daysFromNow(15)),
    );
    await page.getByLabel("Unavailable until: time").fill("16:00");

    await page.getByRole("button", { name: "Confirm the return" }).click();
    // The block would take the unit from a later booking; the sheet names it
    // and offers to move it to the free unit of the same model.
    await expect(page.getByText(/This block takes an asset booked by/)).toBeVisible(
      { timeout: 15000 },
    );
    const move = page.getByRole("checkbox", {
      name: /Move E2E Later .* to another unit of the same model/,
    });
    await expect(move).toBeChecked();
    await page.getByRole("button", { name: "Confirm the return" }).click();
    await expect(
      page.getByRole("heading", { name: "Return", exact: true }),
    ).toBeHidden({ timeout: 15000 });

    const moved = await api.getRentalBooking(token, laterId);
    const lines = moved.lines as Array<{ item_id: string }>;
    expect(lines[0].item_id).toBe(returnUnits[1]);

    const returned = await api.getRentalBooking(token, returningId);
    expect(returned.status).toBe("RETURNED");
  });
});
