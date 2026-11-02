import { test, expect } from "./fixtures/auth";

/**
 * Warehouse Configuration is split into sections and has one Save for the
 * whole page: it appears when something changed, covers edits from several
 * sections, and the page asks before it is left with unsaved work.
 */
test.describe("Warehouse — Configuration", () => {
  test("one Save covers edits made in different sections", async ({
    page,
    authenticatedPage,
  }) => {
    await page.goto("/warehouse/settings");
    await expect(
      page.getByRole("tab", { name: "Receiving and scanning" }),
    ).toBeVisible();
    await expect(page.getByRole("button", { name: "Save" })).toHaveCount(0);

    await page.getByRole("tab", { name: "Work on the floor" }).click();
    const confirmByScan = page.getByRole("checkbox", {
      name: /confirm the location by scan/i,
    });
    const wasChecked = await confirmByScan.isChecked();
    await confirmByScan.setChecked(!wasChecked);

    await page.getByRole("tab", { name: "Numbering and prices" }).click();
    const tracking = page.getByRole("checkbox", {
      name: /enable value tracking/i,
    });
    const trackingWas = await tracking.isChecked();
    await tracking.setChecked(!trackingWas);

    // One Save, whichever section is open.
    await expect(page.getByRole("button", { name: "Save" })).toHaveCount(1);
    await page.getByRole("button", { name: "Save" }).click();
    await expect(page.getByText("You have unsaved changes")).toHaveCount(0);

    // Both edits were kept.
    await page.reload();
    await page.getByRole("tab", { name: "Work on the floor" }).click();
    await expect(
      page.getByRole("checkbox", { name: /confirm the location by scan/i }),
    ).toBeChecked({ checked: !wasChecked });
    await page.getByRole("tab", { name: "Numbering and prices" }).click();
    await expect(
      page.getByRole("checkbox", { name: /enable value tracking/i }),
    ).toBeChecked({ checked: !trackingWas });

    // Both settings are organisation-wide and every other spec shares them:
    // put them back, or the floor specs that run after this one see receiving
    // sessions that ask for a shelf scan.
    await page
      .getByRole("checkbox", { name: /enable value tracking/i })
      .setChecked(trackingWas);
    await page.getByRole("tab", { name: "Work on the floor" }).click();
    await page
      .getByRole("checkbox", { name: /confirm the location by scan/i })
      .setChecked(wasChecked);
    await page.getByRole("button", { name: "Save" }).click();
    await expect(page.getByText("You have unsaved changes")).toHaveCount(0);
    await page.reload();
    await page.getByRole("tab", { name: "Work on the floor" }).click();
    await expect(
      page.getByRole("checkbox", { name: /confirm the location by scan/i }),
    ).toBeChecked({ checked: wasChecked });
  });

  test("leaving with an unsaved change asks first", async ({
    page,
    authenticatedPage,
  }) => {
    await page.goto("/warehouse/settings");
    await page.getByRole("tab", { name: "Work on the floor" }).click();
    await page
      .getByRole("checkbox", { name: /confirm the location by scan/i })
      .click();

    await page
      .getByRole("navigation", { name: "Module navigation" })
      .getByRole("link", { name: "History" })
      .click();

    await expect(page.getByText(/holds unsaved changes/i)).toBeVisible();
    await page.getByRole("button", { name: "Cancel" }).click();
    await expect(page).toHaveURL(/\/warehouse\/settings/);
  });
});
