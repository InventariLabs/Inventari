import { randomUUID } from "node:crypto";

import { test, expect } from "./fixtures/auth";
import { ApiHelper } from "./helpers/api";
import { ADMIN_EMAIL, ADMIN_PASSWORD } from "./fixtures/credentials";

/**
 * A copy the browser refuses ends in a sheet that shows the text: the usual
 * self-hosted install is reached over plain `http://` on a LAN address, where
 * `navigator.clipboard` does not exist. The invitation row's "Copy link" is
 * the first place an administrator meets it.
 */
test.describe("Copy by hand — an invitation link with no clipboard", () => {
  let email: string;
  let code: string;

  // Each test invites an address of its own, just before it opens the list.
  // The suite runs fully parallel, so a worker can take this file's tests in
  // several groups and runs a beforeAll once per group: one address drawn
  // per file is then invited twice, and its row's menu button names two
  // rows. Inviting last also keeps the row inside the newest twenty the
  // list shows while other specs invite in parallel.
  test.beforeEach(async ({ page, playwright, baseURL, authenticatedPage }) => {
    const ctx = await playwright.request.newContext({ baseURL });
    const api = new ApiHelper(ctx);
    const { access_token } = await api.login(ADMIN_EMAIL, ADMIN_PASSWORD);
    email = `copy-by-hand-${randomUUID().slice(0, 8)}@example.com`;
    code = (await api.createInvite(access_token, email)).invite_code;
    await ctx.dispose();

    // What an insecure context looks like to the page.
    await page.addInitScript(() => {
      Object.defineProperty(navigator, "clipboard", {
        value: undefined,
        configurable: true,
      });
    });
    await page.goto("/settings");
  });

  async function openSheet(page: import("@playwright/test").Page) {
    const trigger = page.getByRole("button", {
      name: `Actions for the invitation to ${email}`,
    });
    await trigger.click();
    await page.getByRole("button", { name: "Copy link" }).click();
    const sheet = page.getByRole("dialog", { name: "Copy by hand" });
    await expect(sheet).toBeVisible({ timeout: 10000 });
    return { trigger, sheet };
  }

  test("shows the whole link, selected, and keeps Tab inside the sheet", async ({
    page,
  }) => {
    const { sheet } = await openSheet(page);

    const field = sheet.getByTestId("manual-copy-value");
    await expect(field).toHaveValue(
      new RegExp(`/join\\?code=${code}$`),
    );
    await expect(field).toBeFocused();

    // Ctrl+C reaches the browser's own copy with the whole link selected.
    await page.evaluate(() => {
      document.addEventListener("copy", () => {
        const el = document.activeElement as HTMLTextAreaElement;
        (window as unknown as { copied: string }).copied = el.value.slice(
          el.selectionStart ?? 0,
          el.selectionEnd ?? 0,
        );
      });
    });
    await page.keyboard.press("Control+c");
    const copied = await page.evaluate(
      () => (window as unknown as { copied: string }).copied,
    );
    expect(copied).toBe(await field.inputValue());

    const done = sheet.getByRole("button", { name: "Done" });
    await page.keyboard.press("Tab");
    await expect(done).toBeFocused();
    await page.keyboard.press("Tab");
    await expect(field).toBeFocused();
    await page.keyboard.press("Shift+Tab");
    await expect(done).toBeFocused();
    await page.keyboard.press("Shift+Tab");
    await expect(field).toBeFocused();
  });

  for (const how of ["Done", "Escape", "backdrop"] as const) {
    test(`closing with ${how} returns focus to the row's menu button`, async ({
      page,
    }) => {
      const { trigger, sheet } = await openSheet(page);

      if (how === "Done") {
        await sheet.getByRole("button", { name: "Done" }).click();
      } else if (how === "Escape") {
        await page.keyboard.press("Escape");
      } else {
        await page.mouse.click(5, 5);
      }

      await expect(sheet).toBeHidden();
      await expect(trigger).toBeFocused();
    });
  }
});
