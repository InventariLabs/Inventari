import { expect, type Locator, type Page } from "@playwright/test";

/**
 * Choose a day in the app's date field: open it, walk the grid to the day's
 * month and press the day, which the grid names in full ("November 5, 2026").
 * `field` is the field's trigger — the combobox that carries its label.
 */
export async function pickDay(page: Page, field: Locator, iso: string) {
  const [year, month, day] = iso.split("-").map(Number);
  await field.click();
  const grid = page.getByRole("grid").last();
  await expect(grid).toBeVisible();
  // The grid is named by its month; walk the difference.
  const shown = new Date(`1 ${await grid.getAttribute("aria-label")}`);
  const steps = (year - shown.getFullYear()) * 12 + (month - 1 - shown.getMonth());
  const nav = page.getByRole("button", {
    name: steps < 0 ? "Previous month" : "Next month",
  });
  for (let i = 0; i < Math.abs(steps); i++) await nav.click();
  await page
    .getByRole("button", {
      name: new Intl.DateTimeFormat("en-US", { dateStyle: "long" }).format(
        new Date(year, month - 1, day),
      ),
      exact: true,
    })
    .click();
}

/** The day, as the date fields write it (`yyyy-MM-dd`), `offset` days from today. */
export function isoDay(offset = 0): string {
  const day = new Date();
  day.setDate(day.getDate() + offset);
  return [
    day.getFullYear(),
    String(day.getMonth() + 1).padStart(2, "0"),
    String(day.getDate()).padStart(2, "0"),
  ].join("-");
}
