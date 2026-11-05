import type { Page } from "@playwright/test";
import { test, expect } from "./fixtures/auth";
import { ApiHelper } from "./helpers/api";
import { ADMIN_EMAIL, ADMIN_PASSWORD } from "./fixtures/credentials";

/**
 * The ways back from an endpoint that is off: Reactivate in the circuit
 * breaker's banner, and Reactivate in the toast that a passing Test on an
 * inactive endpoint leaves behind.
 *
 * The breaker itself needs as many failing deliveries as the organization's
 * threshold, so the tripped state is read from the real list and marked on
 * the way to the page (`auto_disabled_at`) for as long as the endpoint is
 * still off. Reactivating goes to the real backend, which is what turns the
 * card back on and ends the marking.
 */

const VIEWPORTS = [
  { label: "desktop", width: 1440, height: 900 },
  { label: "phone", width: 390, height: 844 },
];

let api: ApiHelper;
let token: string;
const created: string[] = [];

async function createInactiveWebhook(label: string) {
  const name = `E2E-Breaker-${label}-${Date.now()}`;
  const webhook = await api.createWebhook(token, {
    name,
    url: "https://example.com/e2e-breaker",
    event_types: ["item.created"],
    is_active: false,
  });
  created.push(webhook.id);
  return { id: webhook.id, name };
}

/** Lists the real endpoints, marking this one as cut off while it is off. */
async function tripWhileOff(page: Page, webhookId: string) {
  await page.route(/\/api\/v1\/webhooks\/endpoints(\?.*)?$/, async (route) => {
    if (route.request().method() !== "GET") return route.fallback();
    const response = await route.fetch();
    const body = await response.json();
    for (const item of body.items) {
      if (item.id === webhookId && !item.is_active) {
        item.auto_disabled_at = new Date().toISOString();
        item.consecutive_failures = 10;
      }
    }
    await route.fulfill({ response, json: body });
  });
}

test.describe("Webhooks — recovery from an endpoint that is off", () => {
  test.beforeAll(async ({ playwright, baseURL }) => {
    const requestContext = await playwright.request.newContext({ baseURL });
    api = new ApiHelper(requestContext);
    token = (await api.login(ADMIN_EMAIL, ADMIN_PASSWORD)).access_token;
    await api.enableAllModules(token);
  });

  // Removed after each test: a leftover endpoint is still off and would put
  // its own Reactivate on the page of the next one.
  test.afterEach(async () => {
    for (const id of created.splice(0)) {
      await api.deleteWebhook(token, id).catch(() => {});
    }
  });

  for (const viewport of VIEWPORTS) {
    test(`a tripped card offers one Reactivate, on one line, at ${viewport.label} width`, async ({
      page,
      authenticatedPage,
    }) => {
      void authenticatedPage;
      await page.setViewportSize(viewport);
      const { id, name } = await createInactiveWebhook(viewport.label);
      await tripWhileOff(page, id);

      await page.goto("/settings/webhooks");
      await expect(page.getByText(name)).toBeVisible({ timeout: 15000 });

      // One door, named after its webhook: the action row below the banner
      // used to offer a second one, spelled out on a phone. The page lists
      // other endpoints too, so the count is of this card's buttons.
      const reactivate = page.getByRole("button", {
        name: new RegExp(`^Reactivate ${name}$`),
      });
      await expect(reactivate).toHaveCount(1);

      // The icon sits beside the word, not above it: stacked, the glyph's
      // centre rides well above the button's.
      const button = (await reactivate.boundingBox())!;
      const icon = (await reactivate.locator("svg").boundingBox())!;
      const label = await reactivate.evaluate((el) => {
        const range = document.createRange();
        range.selectNodeContents(
          [...el.childNodes].find((n) => n.nodeType === Node.TEXT_NODE)!,
        );
        const { x, y, width, height } = range.getBoundingClientRect();
        return { x, y, width, height };
      });
      expect(
        Math.abs(icon.y + icon.height / 2 - (button.y + button.height / 2)),
      ).toBeLessThan(4);
      expect(icon.x + icon.width).toBeLessThanOrEqual(label.x + 1);
    });
  }

  test("Reactivate in the banner turns a cut-off endpoint back on", async ({
    page,
    authenticatedPage,
  }) => {
    void authenticatedPage;
    const { id, name } = await createInactiveWebhook("banner");
    await tripWhileOff(page, id);

    await page.goto("/settings/webhooks");
    await expect(
      page.getByRole("button", { name: `Reactivate ${name}` }),
    ).toBeVisible({ timeout: 15000 });

    await page.getByRole("button", { name: `Reactivate ${name}` }).click();

    await expect(page.getByText("Webhook reactivated")).toBeVisible({
      timeout: 10000,
    });
    await expect(
      page.getByRole("button", { name: `Reactivate ${name}` }),
    ).toHaveCount(0);
    const [stored] = (await api.listWebhooks(token)).filter((w) => w.id === id);
    expect(stored).toMatchObject({ is_active: true });
  });

  test("a passing Test on an off endpoint says it is still off, and its Reactivate switches it on", async ({
    page,
    authenticatedPage,
  }) => {
    void authenticatedPage;
    const { id, name } = await createInactiveWebhook("toast");
    // The receiver is not the subject here: answer the test as a healthy one.
    await page.route(`**/api/v1/webhooks/endpoints/${id}/test`, (route) =>
      route.fulfill({
        json: {
          success: true,
          status_code: 200,
          error: null,
          delivery_id: null,
        },
      }),
    );

    await page.goto("/settings/webhooks");
    await expect(page.getByText(name)).toBeVisible({ timeout: 15000 });

    await page.getByRole("button", { name: `Test ${name}` }).click();

    const toast = page.getByText(/Test ping passed \(200\).*still off/);
    await expect(toast).toBeVisible({ timeout: 10000 });
    // The test left the endpoint where it was.
    expect(
      (await api.listWebhooks(token)).find((w) => w.id === id),
    ).toMatchObject({ is_active: false });

    await page
      .locator("[data-sonner-toast]")
      .filter({ has: toast })
      .getByRole("button", { name: "Reactivate" })
      .click();

    await expect(page.getByText("Webhook reactivated")).toBeVisible({
      timeout: 10000,
    });
    await expect
      .poll(async () =>
        (await api.listWebhooks(token)).find((w) => w.id === id),
      )
      .toMatchObject({ is_active: true });
  });
});
