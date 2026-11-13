import { test, expect } from "./fixtures/auth";
import { ApiHelper } from "./helpers/api";
import { expectApiOk } from "./helpers/page-load";
import { ADMIN_EMAIL, ADMIN_PASSWORD } from "./fixtures/credentials";

/**
 * responsive smoke: table at desktop width, enriched cards at mobile.
 *
 * Unit tests cannot catch these regressions — JSDOM has zero-width viewports,
 * so both the table and the card trees are always in the DOM there. Only a
 * real browser applies the `md:` breakpoints that pick one or the other.
 */

test.describe("Equipment — asset list responsive smoke", () => {
  let api: ApiHelper;
  let token: string;
  const createdIds: string[] = [];
  const assignmentIds: string[] = [];
  let categoryId = "";
  // The `chromium` and `mobile` projects both run this file, in parallel,
  // against one shared organization. Scoping the fixtures by project name
  // keeps each run's teardown off the other run's rows — a shared category
  // is deletable by whichever project finishes first.
  let assignee = "E2E Assignee";
  // Carried by this project's asset names, so a search for it lists them and
  // nothing else the organization holds.
  let tag = "";

  test.beforeAll(async ({ playwright, baseURL }, workerInfo) => {
    // A worker that leaves this describe for another file's test and comes
    // back runs this hook again on the same arrays; the ids of the round
    // before name rows its `afterAll` has deleted, and the first of them
    // is the one checked out below.
    createdIds.length = 0;
    assignmentIds.length = 0;
    const requestContext = await playwright.request.newContext({ baseURL });
    api = new ApiHelper(requestContext);
    const authData = await api.login(ADMIN_EMAIL, ADMIN_PASSWORD);
    token = authData.access_token;

    // Unique per beforeAll round, not per project: each worker of this file
    // seeds its own pair, and two workers sharing one tag list each other's
    // rows in the same search. A sibling's Alpha, created between its two
    // POSTs, is then the newest row and sorts above this worker's Zulu.
    const scope = workerInfo.project.name;
    const unique = `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`;
    tag = `responsive-${scope}-${unique}`;
    assignee = `E2E Assignee ${tag}`;

    const storages = await api.listStorages(token);
    const storageId = process.env.E2E_STORAGE_ID || storages[0]?.id || "";

    const category = await api.createCategoryIdempotent(token, {
      name: `E2E-Responsive-${tag}`,
      context_tag: "equipment",
    });
    categoryId = category.id;

    // Names stay prefixed with Zulu/Alpha: the sort assertion below reads the
    // prefix, and the tag separates the two projects' rows. Alpha is created
    // first and Zulu last, so the default newest-first order lists Zulu first
    // and only a real name sort can put Alpha on top.
    for (const name of [`Alpha Monitor ${tag}`, `Zulu Laptop ${tag}`]) {
      const item = await api.createEquipmentItem(token, {
        name,
        quantity: 1,
        location_id: storageId,
        category_id: categoryId,
        metadata: { equipment: { equipment_status: "AVAILABLE" } },
      });
      createdIds.push(item.id);
    }
    const assignment = await api.checkoutAsset(token, {
      item_id: createdIds[1],
      assigned_to_name: assignee,
    });
    assignmentIds.push(assignment.id);
  });

  test.afterAll(async () => {
    // Check in before deleting: the equipment interceptor blocks deleting
    // an asset with an open assignment, which left ghost rows behind on
    // earlier runs.
    for (const id of assignmentIds) {
      await api.checkinAsset(token, id).catch(() => {});
    }
    for (const id of createdIds) {
      await api.deleteItem(token, id).catch(() => {});
    }
    if (categoryId) {
      await api.deleteCategory(token, categoryId).catch(() => {});
    }
  });

  test("desktop (1440px): table answers where and who, and sorts by name", async ({
    page,
    authenticatedPage,
  }) => {
    await page.setViewportSize({ width: 1440, height: 1000 });
    // Under a full-suite 8-worker load the first request can take longer
    // than the 15s default — give it headroom instead of flaking.
    const loaded = expectApiOk(page, "/api/v1/equipment/assets", {
      timeout: 30000,
    });
    await page.goto("/equipment/assets");
    await loaded;

    // Table, not cards: sortable header + the where/who columns.
    await expect(
      page.getByRole("button", { name: /sort by name/i }),
    ).toBeVisible({ timeout: 15000 });
    await expect(
      page.getByRole("button", { name: /sort by location/i }),
    ).toBeVisible();
    await expect(
      page.getByText("Held by", { exact: true }).first(),
    ).toBeVisible();

    // Sorting by name asc puts Alpha Monitor first, while the default
    // created_at desc order puts Zulu Laptop first (asserted below before the
    // click), so the final assertion fails when the name sort is ignored. Only this project's rows
    // are listed: which asset of the whole organization sorts first depends
    // on what else the stack holds — the demo data's "APC Smart-UPS" did.
    const searched = expectApiOk(
      page,
      new RegExp(`/api/v1/equipment/assets\\?.*search=${tag}`),
    );
    await page.getByRole("textbox", { name: "Search assets…" }).fill(tag);
    await searched;
    await expect(
      page.locator("table tbody tr").filter({ hasNotText: tag }),
    ).toHaveCount(0);
    await expect(page.locator("table tbody tr").first()).toContainText(
      "Zulu Laptop",
    );
    const sortLoaded = expectApiOk(
      page,
      /\/api\/v1\/equipment\/assets\?.*sort=name/,
    );
    await page.getByRole("button", { name: /sort by name/i }).click();
    await sortLoaded;
    await expect(page.locator("table tbody tr").first()).toContainText(
      "Alpha Monitor",
    );
  });

  test("mobile (390px): cards carry location and assignee", async ({
    page,
    authenticatedPage,
  }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    // Same headroom as the desktop sibling: under full-suite load the first
    // request can exceed the 15s default.
    const loaded = expectApiOk(page, "/api/v1/equipment/assets", {
      timeout: 30000,
    });
    await page.goto("/equipment/assets");
    await loaded;

    await expect(
      page.getByText("Zulu Laptop").filter({ visible: true }).first(),
    ).toBeVisible({ timeout: 15000 });
    await expect(
      page
        .getByText(new RegExp(`Held by ${assignee}`))
        .filter({ visible: true })
        .first(),
    ).toBeVisible();
  });

  test("mobile (390px): every action of a selection is on screen", async ({
    page,
    authenticatedPage,
  }) => {
    // Eight actions in one floating bar: a row that scrolled sideways left
    // Retire, Archive and Print labels past the edge with nothing saying
    // more followed. Only a real layout can say where each one lands.
    await page.setViewportSize({ width: 390, height: 844 });
    const searched = expectApiOk(
      page,
      new RegExp(`/api/v1/equipment/assets\\?.*search=${tag}`),
      { timeout: 30000 },
    );
    await page.goto("/equipment/assets");
    await page.getByRole("textbox", { name: "Search assets…" }).fill(tag);
    await searched;
    // `.first()`: kept from when workers shared one tag; the search now lists
    // this worker's pair alone, so the match is unique either way.
    await page
      .getByRole("checkbox", { name: `Select asset Zulu Laptop ${tag}` })
      .first()
      .check({ timeout: 15000 });

    const bar = page.getByRole("toolbar");
    await expect(bar).toBeVisible();
    const buttons = bar.getByRole("button");
    // Clear plus Status, Location, Assign, Return, Retire, Archive and
    // Print labels — the printer button joins them where one is set up.
    const count = await buttons.count();
    expect(count).toBeGreaterThanOrEqual(8);
    for (let i = 0; i < count; i++) {
      await expect(buttons.nth(i)).toBeInViewport({ ratio: 1 });
    }
  });
});
