import { type Page } from "@playwright/test";

/**
 * Codes and labels → the place the table is filtered to. The field searches
 * the server by what is typed, so a place is named by typing it, then picked
 * by its own name; a place inside another says whose it is in its caption,
 * so `path` ("Warehouse → Zone") picks the one under that parent, and a
 * bare name picks the top-level place of that name.
 */
export async function pickLocationSettingsPlace(page: Page, path: string) {
  const names = path.split(" → ");
  const name = names[names.length - 1];
  const parent = names[names.length - 2];
  await page.getByRole("combobox", { name: "Location" }).click();
  await page.getByRole("dialog").getByRole("textbox").fill(name);
  // A row reads "name caption": a top-level place is the one whose whole
  // name is its own, a place inside another starts with its name, then the
  // place it stands in.
  const escape = (text: string) => text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const option = parent
    ? page.getByRole("button", {
        name: new RegExp(`^${escape(name)} ${escape(parent)}`),
      })
    : page.getByRole("button", { name, exact: true });
  await option.first().click();
}
