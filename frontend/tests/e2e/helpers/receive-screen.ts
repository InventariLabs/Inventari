import { expect, type Page } from "@playwright/test";

/**
 * The moves a person makes on the Receive screen, one function each, so the
 * walks read as the delivery they follow and a change to a picker is mended
 * in one place.
 */

export type Source = "supplier" | "return" | "internal";

const SOURCE_RADIO: Record<Source, RegExp> = {
  supplier: /From a supplier/,
  return: /A customer's return/,
  internal: /An internal receipt/,
};

/**
 * Open the Receive screen and wait until it is drawn. Under load the first
 * paint can take longer than the default 5 s, and a step that starts over a
 * blank page (or the 404 a failed module list leaves) fails on the page, not
 * on the screen it is about.
 */
export async function openReceive(page: Page) {
  await page.goto("/warehouse/receive");
  await expect(
    page.getByRole("radio", { name: SOURCE_RADIO.supplier }),
  ).toBeVisible({ timeout: 30000 });
}

export async function chooseSource(page: Page, source: Source) {
  await page.getByRole("radio", { name: SOURCE_RADIO[source] }).click();
}

/** The partner field: a supplier, or the customer of a return. */
export async function choosePartner(
  page: Page,
  name: string,
  source: Exclude<Source, "internal"> = "supplier",
) {
  await page.getByRole("combobox", { name: "From" }).click();
  await page
    .getByPlaceholder(
      source === "return" ? "Search customers" : "Search suppliers",
    )
    .fill(name);
  await page.getByRole("button", { name, exact: true }).click();
  await expect(page.getByRole("combobox", { name: "From" })).toContainText(
    name,
  );
}

export async function chooseLocation(page: Page, name: string) {
  await page.getByRole("combobox", { name: "To location" }).click();
  await page.getByPlaceholder("Search locations").fill(name);
  await page.getByRole("button", { name, exact: true }).click();
  await expect(
    page.getByRole("combobox", { name: "To location" }),
  ).toContainText(name);
}

/** A scanner types the code and presses Enter; a person does the same. */
export async function scanProduct(page: Page, code: string, name: string) {
  const scan = page.getByRole("combobox", { name: "Scan or search a product" });
  await scan.fill(code);
  await scan.press("Enter");
  // The row is the proof the scan was understood.
  await expect(
    page
      .getByRole("textbox", { name: `How many arrived: ${name}` })
      .or(page.getByRole("spinbutton", { name: `How many arrived: ${name}` })),
  ).toBeVisible();
}

/**
 * The receiving session a phone opens on a receipt: its card is the product in
 * hand, its footer the one button that moves on.
 */
export function session(page: Page) {
  return page.getByRole("dialog").first();
}

/**
 * Scan a location label into the session's scan field. With the rule that
 * asks for the shelf's label on, the session says so when it has taken it;
 * with the rule off the scan is only taken in and the field empties.
 */
export async function scanShelf(
  page: Page,
  code: string,
  { confirmed = true }: { confirmed?: boolean } = {},
) {
  const field = page.getByRole("textbox", {
    name: "Scan the next product, in any order",
  });
  await field.fill(code);
  await field.press("Enter");
  if (confirmed) {
    await expect(
      page.getByText("Location confirmed", { exact: true }),
    ).toBeVisible();
  } else {
    await expect(field).toHaveValue("");
  }
}

/** The count on the card of the product in hand. */
export function countField(page: Page, product: string) {
  return page.getByRole("spinbutton", {
    name: `How many of ${product} arrived`,
  });
}

/** The count of a product on the sheet: a box on a desk, a stepper on a phone. */
export function arrivedField(page: Page, name: string) {
  return page
    .getByRole("textbox", { name: `How many arrived: ${name}` })
    .or(page.getByRole("spinbutton", { name: `How many arrived: ${name}` }));
}
