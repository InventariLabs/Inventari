import { test, expect } from "./fixtures/auth";

/**
 * The onboarding wizard at a phone width, measured in a real browser.
 *
 * JSDOM has no layout, so a class-name assertion would pass on a footer whose
 * pieces already sit off the screen. At 360 px the currency block kept its
 * 192 px select beside the hint, the button row followed to the right of both
 * and nothing wrapped: the page grew sideways and "Get started" sat at
 * x=397..537, outside the screen — 90 px of overflow on the first step and
 * 177 px on the second, where the back button joins the row. The footer is
 * the assertion here: no horizontal scroll, and the primary action inside
 * the screen on both steps.
 */

/** A whole list as the one page the endpoint answers with. */
const onePage = <T>(items: T[]) => ({
  items,
  total: items.length,
  limit: 200,
  offset: 0,
  has_more: false,
});

// Three profiles and the one-module card: as many cards as the real first-run
// screen carries, so the wizard is taller than the phone and starts at the top
// of the page — the state the fixed strip and the header collide in.
const profiles = [
  {
    id: "food_home",
    name: "Food & Home",
    description: "Track what is in the fridge and what you can cook.",
    default_modules: ["items"],
    suggested_modules: ["recipes"],
  },
  {
    id: "equipment_wms",
    name: "Equipment & Warehouse",
    description: "Track IT assets and equipment with warehouse procurement.",
    default_modules: ["items"],
  },
  {
    id: "clean_core",
    name: "Custom",
    description: "No industry preset — a neutral base you shape yourself.",
    default_modules: ["items"],
  },
];

const catalogue = [
  {
    name: "items",
    display_name: "Inventory",
    description: "The things you have",
    icon: "Box",
    is_always_on: true,
  },
  {
    name: "recipes",
    display_name: "Recipes",
    description: "Cook from what you have",
    icon: "ChefHat",
    is_always_on: false,
  },
];

/**
 * The floating strip is positioned against the viewport while the header
 * scrolls under it: on a phone the wordmark and "EN / Sign out" sat on top of
 * each other. Both are measured as boxes, because whether one covers the
 * other is not a class anyone can point at.
 */
async function expectWordmarkClearOfTheStrip(
  page: import("@playwright/test").Page,
) {
  await page.evaluate(() => window.scrollTo(0, 0));
  const wordmark = (await page
    .getByText("Inventari", { exact: true })
    .boundingBox())!;
  const strip = [
    (await page.getByRole("button", { name: /^EN, Language/ }).boundingBox())!,
    (await page.getByRole("button", { name: /sign out/i }).boundingBox())!,
  ];
  const left = Math.min(...strip.map((b) => b.x));
  const top = Math.min(...strip.map((b) => b.y));
  const right = Math.max(...strip.map((b) => b.x + b.width));
  const bottom = Math.max(...strip.map((b) => b.y + b.height));
  const overlap =
    wordmark.x < right &&
    wordmark.x + wordmark.width > left &&
    wordmark.y < bottom &&
    wordmark.y + wordmark.height > top;
  expect(overlap).toBe(false);
}

async function expectInsideTheScreen(
  page: import("@playwright/test").Page,
  button: import("@playwright/test").Locator,
) {
  // Under mobile emulation `innerWidth` grows with the overflowing content,
  // so the width the page was asked to fit in is the one to compare against.
  const width = await page.evaluate(() =>
    Math.max(
      document.documentElement.scrollWidth,
      document.body.scrollWidth,
    ),
  );
  expect(width).toBeLessThanOrEqual(360);

  const box = await button.boundingBox();
  expect(box).not.toBeNull();
  expect(box!.x).toBeGreaterThanOrEqual(0);
  expect(box!.x + box!.width).toBeLessThanOrEqual(360);
}

test.describe("Onboarding — phone width", () => {
  test.use({ viewport: { width: 360, height: 844 } });

  test.beforeEach(async ({ page, authenticatedPage }) => {
    // Matched on the path: the reader asks for the list a page at a time,
    // so the address carries `limit` and `offset`.
    await page.route(
      (url) => url.pathname === "/api/v1/profiles",
      (route) => route.fulfill({ json: onePage(profiles) }),
    );
    await page.route("**/api/v1/organizations/my", (route) =>
      route.fulfill({ json: { id: "org-e2e", onboarding_completed: false } }),
    );
    await page.route(
      (url) => url.pathname === "/api/v1/modules/available",
      (route) => route.fulfill({ json: onePage(catalogue) }),
    );
    await page.route("**/api/v1/modules/my", (route) =>
      route.fulfill({ json: ["items"] }),
    );
  });

  test("the first step keeps its primary button on the screen", async ({
    page,
  }) => {
    await page.goto("/onboarding");

    // The primary button only becomes "Continue" once a mode is chosen —
    // before that it is the disabled "Get started".
    await page.getByRole("button", { name: /Food & Home/i }).click();
    const next = page.getByRole("button", { name: /continue/i });
    await expect(next).toBeVisible({ timeout: 15000 });
    await expectInsideTheScreen(page, next);
    await expectWordmarkClearOfTheStrip(page);
  });

  test("the second step keeps its primary button on the screen", async ({
    page,
  }) => {
    await page.goto("/onboarding");

    await page.getByRole("button", { name: /Food & Home/i }).click();
    await page.getByRole("button", { name: /continue/i }).click();

    const start = page.getByRole("button", { name: /get started/i });
    await expect(start).toBeVisible({ timeout: 15000 });
    await expectInsideTheScreen(page, start);
    await expectWordmarkClearOfTheStrip(page);
  });
});
