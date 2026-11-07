import type { Page, Response } from "@playwright/test";
import { test, expect } from "./fixtures/auth";
import { ApiHelper } from "./helpers/api";
import { ADMIN_EMAIL, ADMIN_PASSWORD } from "./fixtures/credentials";

/**
 * The stock list narrowed by a search and a place hands both to the report
 * of a day, and the report's two files are asked for the same narrowing.
 *
 * Every step was covered on its own — the list's search in a unit test, the
 * report's in another, the files' parameters in a third — and no test walked
 * the screens in a browser: a link that dropped the search on the way, or a
 * file asked for the whole warehouse, passed them all.
 */
test("the stock on a date keeps the search and the place the stock list was narrowed to", async ({
  page,
  request,
  authenticatedPage,
}, testInfo) => {
  void authenticatedPage;
  const suffix = `${Date.now()}-w${testInfo.workerIndex}`;
  const searched = `rye-${suffix}`;
  const wanted = `E2E ${searched} on the shelf`;
  const elsewhere = `E2E ${searched} elsewhere`;
  const unsearched = `E2E salt-${suffix} on the shelf`;
  const roomName = `E2E As-of room ${suffix}`;
  const api = new ApiHelper(request);
  const token = (await api.login(ADMIN_EMAIL, ADMIN_PASSWORD)).access_token;
  const storages: string[] = [];
  const items: string[] = [];
  try {
    const room = await api.createStorage(token, { name: roomName });
    storages.push(room.id);
    const shelf = await api.createStorage(token, {
      name: `E2E As-of shelf ${suffix}`,
      parent_id: room.id,
    });
    storages.push(shelf.id);
    const other = await api.createStorage(token, {
      name: `E2E As-of other room ${suffix}`,
    });
    storages.push(other.id);
    for (const [name, location] of [
      [wanted, shelf.id],
      [elsewhere, other.id],
      [unsearched, shelf.id],
    ] as const) {
      items.push(
        (
          await api.createItem(token, {
            name,
            quantity: 2,
            unit: "pcs",
            location_id: location,
          })
        ).id,
      );
    }

    // The stock list, narrowed by what the reader types and then by a place:
    // the room holds the shelf, and a place answers for what lies below it.
    await page.goto("/inventory/stock");
    await page
      .getByRole("textbox", { name: "Search a product or a batch…" })
      .fill(searched);
    await expect(page.getByRole("cell", { name: wanted })).toBeVisible({
      timeout: 15000,
    });
    await expect(page.getByRole("cell", { name: elsewhere })).toBeVisible();
    await expect(page.getByRole("cell", { name: unsearched })).toHaveCount(0);

    await page.getByRole("button", { name: "Filter" }).click();
    await page.getByRole("combobox", { name: "Location" }).click();
    await page
      .getByRole("textbox", { name: "Search", exact: true })
      .fill(roomName);
    // A place at the root is named by itself; the shelf below it carries the
    // room's name too, as the way to it.
    await page.getByRole("button", { name: roomName, exact: true }).click();
    await expect(page.getByRole("cell", { name: elsewhere })).toHaveCount(0);
    await expect(page.getByRole("cell", { name: wanted })).toBeVisible();

    // The button carries both to the report of a day.
    await page.getByRole("button", { name: "Stock on a date" }).click();
    await expect(page).toHaveURL(/\/inventory\/stock\/as-of\?/);
    const address = new URL(page.url());
    expect(address.searchParams.get("search")).toBe(searched);
    expect(address.searchParams.get("location")).toBe(room.id);
    await expect(
      page.getByRole("textbox", { name: "Search a product…" }),
    ).toHaveValue(searched);

    // The report's rows are the narrowed ones: the searched product on the
    // shelf below the room, not its namesake elsewhere nor its neighbour.
    await expect(page.getByRole("cell", { name: wanted })).toBeVisible({
      timeout: 15000,
    });
    await expect(page.getByRole("cell", { name: "2 pcs." })).toBeVisible();
    await expect(page.getByRole("cell", { name: elsewhere })).toHaveCount(0);
    await expect(page.getByRole("cell", { name: unsearched })).toHaveCount(0);

    // Both files are asked for what the screen shows.
    for (const [button, path] of [
      ["Export", "/api/v1/stock-as-of/export/xlsx"],
      ["Print", "/api/v1/stock-as-of/export/pdf"],
    ] as const) {
      const file = await fileAskedFor(page, button, path);
      const asked = new URL(file.url());
      expect(asked.searchParams.get("search")).toBe(searched);
      expect(asked.searchParams.get("location_id")).toBe(room.id);
      expect(file.status()).toBe(200);
    }
  } finally {
    for (const id of items) await api.deleteItem(token, id).catch(() => {});
    for (const id of storages.reverse())
      await api.deleteStorage(token, id).catch(() => {});
  }
});

/** The response to the file a button asks for. */
async function fileAskedFor(
  page: Page,
  button: string,
  path: string,
): Promise<Response> {
  const [response] = await Promise.all([
    page.waitForResponse((answer) => new URL(answer.url()).pathname === path),
    page.getByRole("button", { name: button, exact: true }).click(),
  ]);
  return response;
}
