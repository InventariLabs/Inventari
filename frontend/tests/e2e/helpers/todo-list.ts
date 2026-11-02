import { expect, type Locator, type Page } from "@playwright/test";

/**
 * Start and the Board show the first hundred tasks and offer "Show more" for
 * the rest. A spec that looks for the task it just made cannot know whether
 * the shared database holds a hundred older ones, so it asks for more until
 * the thing it looks for is on screen — or the list has nothing more to show.
 */
export async function showMoreUntilVisible(
  page: Page,
  target: Locator,
  timeout = 30000,
): Promise<void> {
  const more = page.getByRole("button", { name: "Show more" });
  await expect(async () => {
    if (await target.first().isVisible()) return;
    if (await more.first().isVisible()) await more.first().click();
    await expect(target.first()).toBeVisible({ timeout: 2000 });
  }).toPass({ timeout });
}
