import { test, expect } from "./fixtures/base";

import { ADMIN_EMAIL, ADMIN_PASSWORD } from "./fixtures/credentials";

test.describe("Scan — label opened while signed out", () => {
  test("signing in continues to the scanned code", async ({ page }) => {
    // The address a printed QR carries, opened by the phone's own camera
    // with no session behind it.
    await page.goto("/s/E2E-SIGNED-OUT-0001");
    await expect(page).toHaveURL(/\/login/);

    await page.fill("#email", ADMIN_EMAIL);
    await page.fill("#password", ADMIN_PASSWORD);
    await page.click('button[type="submit"]');

    // The code survives the sign-in: the scanner opens on it, not on the
    // organization's home route.
    await expect(page).toHaveURL(
      /\/inventory\/scan\?code=E2E-SIGNED-OUT-0001/,
      {
        timeout: 15000,
      },
    );
  });
});
