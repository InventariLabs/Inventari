import { test, expect } from "./fixtures/base";

/**
 * The auth layout owns exactly one first-level heading in the accessibility
 * tree at every width.
 *
 * The brand mark is rendered twice — a large one in the desktop panel and a
 * small one above the mobile form — and exactly one of the two panels is on
 * screen at any width. Whichever carries the heading, a reader at that width
 * must find exactly one `heading` level 1 and never zero: the phone-first
 * layout once shipped with the only h1 parked inside the desktop panel's
 * `hidden lg:flex`, so below 1024px the page had no first-level heading at
 * all, and a DOM count in jsdom could not see it (no CSS there).
 */
const LEVEL_1 = 'h1, [role="heading"][aria-level="1"]';

async function expectExactlyOneLevel1Heading(page: import("@playwright/test").Page) {
	const visible = page.locator(LEVEL_1).filter({
		visible: true,
	});
	await expect(visible).toHaveCount(1);
}

test.describe("the auth layout's first-level heading", () => {
	test("is exactly one, in the accessibility tree, at phone width", async ({
		page,
	}) => {
		await page.setViewportSize({ width: 390, height: 844 });
		await page.goto("/login");
		await expect(page.locator("#email")).toBeVisible();
		await expectExactlyOneLevel1Heading(page);
	});

	test("is exactly one, in the accessibility tree, at desktop width", async ({
		page,
	}) => {
		await page.setViewportSize({ width: 1280, height: 800 });
		await page.goto("/login");
		await expect(page.locator("#email")).toBeVisible();
		await expectExactlyOneLevel1Heading(page);
	});
});
