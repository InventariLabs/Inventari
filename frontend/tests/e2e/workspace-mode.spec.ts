import { test, expect, type Page } from "./fixtures/auth";
import { ADMIN_EMAIL, ADMIN_PASSWORD } from "./fixtures/credentials";
import { ApiHelper } from "./helpers/api";

/**
 * Workspace mode — discoverability & switch flow. Runs serially against
 * the live stack: the apply test mutates
 * the org's active profile and restores it afterwards.
 *
 * The profile choice lives on "My modules" since it merged with the
 * single-module switch; /settings/workspace only redirects there.
 *
 * Covers:
 *   1. Settings sidebar exposes a "My modules" entry with the profile choice.
 *   2. Selecting a profile radio shows what will change (no Preview button).
 *   3. Apply via ConfirmDialog repaints --color-primary-500 and persists
 *      the new active_profile_id.
 *   4. The Launcher header shows the active-profile pill.
 *   5. The org is switched back to its original profile.
 */

const WORKSPACE_URL = "/settings/my-modules";

async function gotoWorkspace(page: Page) {
  await page.goto(WORKSPACE_URL);
  await page
    .waitForLoadState("networkidle", { timeout: 15000 })
    .catch(() => {});
}

/** Name (aria-label) of the radio marked with the CURRENT badge. */
async function currentProfileName(page: Page): Promise<string> {
  const badge = page.getByText(/^current$/i).first();
  await expect(badge).toBeVisible({ timeout: 15000 });
  const radio = page
    .locator("li", { has: badge })
    .locator('input[type="radio"]');
  const name = await radio.getAttribute("aria-label");
  if (!name) throw new Error("Current profile radio has no aria-label");
  return name;
}

/** Pick a target profile different from the current one. */
function otherProfile(currentName: string): string {
  return /food/i.test(currentName) ? "Equipment & Warehouse" : "Food & Home";
}

async function primaryColor(page: Page): Promise<string> {
  return page.evaluate(() =>
    getComputedStyle(document.documentElement)
      .getPropertyValue("--color-primary-500")
      .trim(),
  );
}

/** Switch to `targetName` through the full UI flow and wait for it to stick. */
async function switchProfile(page: Page, targetName: string) {
  await page.getByRole("radio", { name: targetName }).click();
  await expect(
    page.getByRole("heading", { name: "What will change" }),
  ).toBeVisible({ timeout: 15000 });
  const applyBtn = page.getByRole("button", { name: "Apply", exact: true });
  await expect(applyBtn).toBeEnabled({ timeout: 15000 });
  await applyBtn.click();

  const dialog = page.getByRole("alertdialog");
  await expect(dialog).toBeVisible({ timeout: 10000 });
  await dialog.getByRole("button", { name: /switch workspace mode/i }).click();

  // The CURRENT badge moves to the target profile once the org refreshes.
  const badge = page.getByText(/^current$/i).first();
  await expect(
    page
      .locator("li", { has: badge })
      .locator(`input[aria-label="${targetName}"]`),
  ).toBeVisible({ timeout: 20000 });
}

test.describe.serial("Workspace mode", () => {
  test("settings sidebar links to My modules with the profile choice", async ({
    page,
    authenticatedPage,
  }) => {
    await page.goto("/settings");
    await page
      .waitForLoadState("networkidle", { timeout: 15000 })
      .catch(() => {});

    const navLink = page.getByRole("link", { name: "My modules", exact: true });
    await expect(navLink).toBeVisible({ timeout: 15000 });
    await navLink.click();

    await expect(page).toHaveURL(new RegExp(WORKSPACE_URL));
    await expect(
      page
        .getByRole("radio", { name: /Food & Home|Equipment & Warehouse/ })
        .first(),
    ).toBeVisible({ timeout: 15000 });
  });

  test("selecting a profile radio auto-fires the preview diff", async ({
    page,
    authenticatedPage,
  }) => {
    await gotoWorkspace(page);
    const target = otherProfile(await currentProfileName(page));

    await page.getByRole("radio", { name: target }).click();

    // The diff appears without clicking any Preview button.
    await expect(
      page.getByRole("heading", { name: "What will change" }),
    ).toBeVisible({ timeout: 15000 });
  });

  test("apply repaints the primary colour, shows the pill, and is reverted", async ({
    page,
    request,
    authenticatedPage,
  }) => {
    // Applying a profile resets the module set to its preset, so switching
    // back restores the profile but not the modules the suite had switched
    // on; the stack is left with the set it had before this test.
    const api = new ApiHelper(request);
    const token = (await api.login(ADMIN_EMAIL, ADMIN_PASSWORD)).access_token;
    const modulesBefore = await api.getMyModules(token);

    await gotoWorkspace(page);
    const original = await currentProfileName(page);
    const target = otherProfile(original);
    const before = await primaryColor(page);

    await switchProfile(page, target);

    // Theme + persisted profile survive a full reload.
    await page.reload();
    await page
      .waitForLoadState("networkidle", { timeout: 15000 })
      .catch(() => {});
    const after = await primaryColor(page);
    expect(after).not.toBe(before);
    expect(await currentProfileName(page)).toBe(target);

    // The Launcher header pill shows the new profile and links to the
    // workspace settings (the Launcher's stable URL is /launcher).
    await page.goto("/launcher");
    await page
      .waitForLoadState("networkidle", { timeout: 15000 })
      .catch(() => {});
    const pill = page.getByRole("link", { name: new RegExp(target) });
    await expect(pill).toBeVisible({ timeout: 15000 });
    await expect(pill).toHaveAttribute("href", WORKSPACE_URL);

    // Restore the org's original profile, then the modules it had.
    await gotoWorkspace(page);
    await switchProfile(page, original);
    const modulesAfter = await api.getMyModules(token);
    for (const module of modulesBefore.filter((m) => !modulesAfter.includes(m)))
      await api.toggleModule(token, module, true).catch(() => {});
  });

  test("header module switcher navigates cross-module; logo opens the launcher", async ({
    page,
    authenticatedPage,
  }) => {
    // /inventory is always-on, so this does not depend on the active profile.
    await page.goto("/inventory/items");
    await page
      .waitForLoadState("networkidle", { timeout: 15000 })
      .catch(() => {});

    const trigger = page.getByRole("button", { name: /switch module/i });
    await expect(trigger).toBeVisible({ timeout: 15000 });
    await trigger.click();

    const menu = page.getByRole("menu");
    await expect(menu).toBeVisible({ timeout: 10000 });
    // An admin's last entry opens My modules (others get "All modules", the
    // launcher); the suite signs in as an admin.
    await expect(
      menu.getByRole("menuitem", { name: "My modules", exact: true }),
    ).toBeVisible();

    // Click the first non-active module entry and expect a route change.
    const items = menu.getByRole("menuitem");
    const count = await items.count();
    let clicked = false;
    for (let i = 0; i < count; i++) {
      const item = items.nth(i);
      const isActive = await item.getAttribute("aria-current");
      const label = (await item.textContent()) ?? "";
      if (!isActive && !/^(my modules|all modules|settings)$/i.test(label.trim())) {
        await item.click();
        clicked = true;
        break;
      }
    }
    expect(clicked).toBe(true);
    await expect(page).not.toHaveURL(/\/inventory\/items/);

    // Logo leads to the launcher hub.
    await page
      .getByRole("link", { name: /^Inventari/ })
      .first()
      .click();
    await expect(page).toHaveURL(/\/launcher/);
  });
});
