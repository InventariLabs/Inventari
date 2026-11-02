import { type Page, type Route } from "@playwright/test";
import { test, expect } from "./fixtures/auth";
import { ApiHelper } from "./helpers/api";
import { ADMIN_EMAIL, ADMIN_PASSWORD } from "./fixtures/credentials";

/**
 * The floor's mishaps at the posting screens: a double press, the same
 * document open in two tabs, a connection that drops mid-post, a server that
 * restarts under the user.
 *
 * Every test reads the stock afterwards through the API, not the screen: the
 * promise is that the shelf is right and the user is told in words what
 * happened, so a green banner on top of a doubled posting must not pass.
 *
 * A server restart is staged as the answer a proxy gives while the server is
 * away (a 502 with an HTML body) on every API call, lifted when the "server"
 * is back. The browser cannot tell that from a restart, and it keeps the
 * run to the isolated stack's own browser.
 */

const POST_NEW = "**/api/v1/warehouse/documents/post";
const API = "**/api/v1/**";

/** What a user must never be shown as a message. */
const RAW_ERROR =
  /\b502\b|bad gateway|network error|axioserror|econnrefused|\[object|undefined|traceback/i;

function proxyDown(route: Route) {
  return route.fulfill({
    status: 502,
    contentType: "text/html",
    body: "<html><body><h1>502 Bad Gateway</h1></body></html>",
  });
}

async function serverAway(page: Page) {
  await page.route(API, proxyDown);
}

async function serverBack(page: Page) {
  await page.unroute(API, proxyDown);
}

test.describe("Stock posting survives the floor's mishaps", () => {
  let api: ApiHelper;
  let token: string;
  let uid: string;
  let shelfId: string;
  let shelfName: string;
  let supplierName: string;
  let counter = 0;

  test.beforeAll(async ({ playwright, baseURL }, testInfo) => {
    // Every run of this setup seeds its own shelf and supplier. The file runs
    // fully parallel: several workers run this setup at once, and a worker
    // that comes back to the file after other tests runs it again. A stamp
    // taken once when the file loaded was the same both times in one worker,
    // and the same in two workers that loaded it in one millisecond; the
    // second createPartner then failed with PARTNER_CONFLICT, or the shelf
    // picker found two shelves of one name, before any assertion ran.
    uid = `${Date.now().toString(36)}-w${testInfo.workerIndex}`;
    const ctx = await playwright.request.newContext({ baseURL });
    api = new ApiHelper(ctx);
    token = (await api.login(ADMIN_EMAIL, ADMIN_PASSWORD)).access_token;
    await api.completeOnboarding(token);
    await api.enableAllModules(token);
    shelfName = `E2E-Mishap-Shelf-${uid}`;
    shelfId = (
      await api.createStorageIdempotent(token, {
        name: shelfName,
        location_type: "SHELF",
      })
    ).id;
    supplierName = `E2E-Mishap-Supplier-${uid}`;
    await api.createPartner(token, { name: supplierName, type: "SUPPLIER" });
  });

  /** A product of its own with twenty on the shelf, so no test sees another's. */
  async function stocked() {
    const name = `E2E-Mishap-Rice-${uid}-${counter++}`;
    const template = await api.createProductTemplate(token, { name });
    const item = await api.createItemForTemplate(token, {
      name,
      template_id: template.id,
      location_id: shelfId,
      quantity: 20,
    });
    return {
      name,
      templateId: template.id,
      itemId: item.id,
      onHand: () => api.quantityOnHand(token, template.id, shelfId),
    };
  }

  async function oneLineOnTheIssueScreen(page: Page, productName: string) {
    await page.goto("/warehouse/issue");
    await page
      .getByRole("radio", { name: /For production or own use/ })
      .click();
    await page.getByRole("combobox", { name: /From location/ }).click();
    await page.getByPlaceholder(/Search location/).fill(shelfName);
    await page.getByRole("button", { name: shelfName }).click();
    await page.getByRole("combobox", { name: /Item/ }).fill(productName);
    await page
      .getByRole("option", { name: new RegExp(productName) })
      .first()
      .click();
  }

  test.describe("the one-screen Issue", () => {
    // Documents behaviour that already held at the screen: the button is
    // disabled while the first press is in flight. The server's key is what
    // covers a repeat that gets past the screen (see the lost-answer test).
    test("a double press posts once", async ({ page, authenticatedPage }) => {
      const rice = await stocked();
      let sent = 0;
      // Slow answer: the second press arrives while the first is in flight.
      await page.route(POST_NEW, async (route) => {
        sent++;
        await new Promise((resolve) => setTimeout(resolve, 800));
        await route.continue();
      });
      await oneLineOnTheIssueScreen(page, rice.name);

      await page.getByRole("button", { name: "Issue for use" }).dblclick();

      await expect(
        page.getByRole("heading", { name: "Issued 1 line" }),
      ).toBeVisible({ timeout: 15000 });
      expect(sent).toBe(1);
      expect(await rice.onHand()).toBe(19);
    });

    test("a request that never reached the server posts nothing, and the retry posts once", async ({
      page,
      authenticatedPage,
    }) => {
      const rice = await stocked();
      let first = true;
      await page.route(POST_NEW, (route) => {
        if (!first) return route.continue();
        first = false;
        return route.abort("connectionreset");
      });
      await oneLineOnTheIssueScreen(page, rice.name);

      await page.getByRole("button", { name: "Issue for use" }).click();

      await expect(page.getByText(/connection dropped/i)).toBeVisible();
      await expect(page.locator("body")).not.toContainText(RAW_ERROR);
      expect(await rice.onHand()).toBe(20);

      // The list is still there; the same button retries.
      await page.getByRole("button", { name: "Issue for use" }).click();
      await expect(
        page.getByRole("heading", { name: "Issued 1 line" }),
      ).toBeVisible({ timeout: 15000 });
      expect(await rice.onHand()).toBe(19);
    });

    test("an answer lost after the server posted is not posted again by the retry", async ({
      page,
      authenticatedPage,
    }) => {
      const rice = await stocked();
      let first = true;
      await page.route(POST_NEW, async (route) => {
        if (!first) return route.continue();
        first = false;
        // The server got it and did it; the answer never gets back.
        await route.fetch();
        return route.abort("connectionreset");
      });
      await oneLineOnTheIssueScreen(page, rice.name);

      await page.getByRole("button", { name: "Issue for use" }).click();

      await expect(page.getByText(/connection dropped/i)).toBeVisible();
      expect(await rice.onHand()).toBe(19);

      await page.getByRole("button", { name: "Issue for use" }).click();
      await expect(
        page.getByRole("heading", { name: "Issued 1 line" }),
      ).toBeVisible({ timeout: 15000 });
      expect(await rice.onHand()).toBe(19);
    });
  });

  test.describe("the same draft in two tabs", () => {
    test("a post from the stale tab is refused and says the document was already posted", async ({
      page,
      authenticatedPage,
    }) => {
      const rice = await stocked();
      const draft = await api.createDocument(token, {
        type: "INTERNAL_OUT",
        source_location_id: shelfId,
        lines: [
          {
            item_id: rice.itemId,
            product_template_id: rice.templateId,
            expected_quantity: 1,
          },
        ],
      });
      const stale = await page.context().newPage();
      await page.goto(`/warehouse/documents/${draft.id}`);
      await stale.goto(`/warehouse/documents/${draft.id}`);
      const issue = (tab: Page) =>
        tab.getByRole("button", { name: "Remove from stock" });
      await expect(issue(page)).toBeVisible({ timeout: 15000 });
      await expect(issue(stale)).toBeVisible({ timeout: 15000 });

      await issue(page).click();
      await page.getByRole("button", { name: "Post", exact: true }).click();
      await expect.poll(() => rice.onHand()).toBe(19);

      await issue(stale).click();
      await stale.getByRole("button", { name: "Post", exact: true }).click();

      await expect(stale.getByText(/already been posted/i)).toBeVisible();
      expect(await rice.onHand()).toBe(19);
    });
  });

  test.describe("a server restart under the user", () => {
    test("on Start: a reload while it is away says so and offers to try again", async ({
      page,
      authenticatedPage,
    }) => {
      await page.goto("/warehouse/todo");
      await expect(page.getByText("What are we doing?")).toBeVisible({
        timeout: 15000,
      });

      await serverAway(page);
      await page.reload();
      await expect(page.getByText("Cannot reach the server")).toBeVisible({
        timeout: 15000,
      });
      await expect(page.locator("body")).not.toContainText(RAW_ERROR);

      await serverBack(page);
      await page.getByRole("button", { name: "Try again" }).click();
      await expect(page.getByText("What are we doing?")).toBeVisible({
        timeout: 15000,
      });
    });

    test("on Receive: the draft survives the failed press and the next one works", async ({
      page,
      authenticatedPage,
    }) => {
      const rice = await stocked();
      await page.goto("/warehouse/todo");
      await page.getByRole("button", { name: /^Receive goods/ }).click();
      await expect(
        page.getByRole("heading", { level: 1, name: "Receive goods" }),
      ).toBeVisible({ timeout: 15000 });

      await page.getByRole("combobox", { name: "From", exact: true }).click();
      const from = page.getByRole("dialog", { name: "From" });
      await from.getByRole("textbox", { name: "Search suppliers" }).fill(supplierName);
      await from.getByRole("button", { name: supplierName }).click();
      await page.getByRole("combobox", { name: "To location" }).click();
      const to = page.getByRole("dialog", { name: "To location" });
      await to.getByRole("textbox").fill(shelfName);
      await to.getByRole("button", { name: shelfName }).click();
      await page
        .getByRole("combobox", { name: "Scan or search a product" })
        .fill(rice.name);
      await page
        .getByRole("option", { name: new RegExp(rice.name) })
        .first()
        .click();

      // "Finish later" saves the draft and opens it — the press that a
      // restart can cut off.
      await serverAway(page);
      await page.getByRole("button", { name: "Finish later" }).click();
      await expect(page.getByText("Could not save the draft.")).toBeVisible();
      await expect(page.locator("body")).not.toContainText(RAW_ERROR);
      // Nothing was written, and what the user typed is still on the form.
      await expect(
        page.getByRole("combobox", { name: "From", exact: true }),
      ).toContainText(supplierName);

      await serverBack(page);
      await page.getByRole("button", { name: "Finish later" }).click();
      await expect(page).toHaveURL(/\/warehouse\/documents\/[0-9a-f-]{36}/, {
        timeout: 15000,
      });
    });

    test("on the phone scan screen: the lookup says to try again, then finds the document", async ({
      page,
      authenticatedPage,
    }) => {
      const rice = await stocked();
      const draft = await api.createDocument(token, {
        type: "INTERNAL_OUT",
        source_location_id: shelfId,
        lines: [
          {
            item_id: rice.itemId,
            product_template_id: rice.templateId,
            expected_quantity: 1,
          },
        ],
      });
      await api.confirmDocument(token, draft.id);
      const { number } = await api.getDocument(token, draft.id);
      await page.setViewportSize({ width: 390, height: 844 });
      await page.goto("/warehouse/scan");
      const field = page.getByRole("textbox").first();
      await field.fill(String(number));

      await serverAway(page);
      await page.getByRole("button", { name: "Find" }).click();
      await expect(page.getByText("Could not look up the code")).toBeVisible();
      await expect(page.locator("body")).not.toContainText(RAW_ERROR);
      await expect(field).toHaveValue(String(number));

      await serverBack(page);
      await page.getByRole("button", { name: "Find" }).click();
      await expect(page).toHaveURL(new RegExp(draft.id), { timeout: 15000 });
    });
  });
});
