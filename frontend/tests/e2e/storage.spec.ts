import type { Page } from "@playwright/test";

import { test, expect } from "./fixtures/auth";
import { ApiHelper } from "./helpers/api";
import { ADMIN_EMAIL, ADMIN_PASSWORD } from "./fixtures/credentials";

/**
 * The Locations screen: a searchable tree of every location beside the one
 * selected, with its path, its tabs and the same actions on every level.
 *
 * Every test makes the location it changes, so the tests run in any order and
 * in parallel: renaming or deleting a location another test is looking for
 * would race it.
 */
test.describe("Locations — tree and selected location", () => {
  let api: ApiHelper;
  let token: string;
  const uniqueId = () => Math.random().toString(36).substring(2, 9);
  const created: string[] = [];

  const makeStorage = async (name: string, parentId?: string) => {
    const storage = await api.createStorage(token, {
      name,
      ...(parentId ? { parent_id: parentId } : {}),
    });
    created.push(storage.id);
    return storage.id;
  };

  // The tree opens a branch at a time, so a name is found through the
  // search: it replaces the tree with the locations that match, each named
  // with its full path.
  const search = async (page: Page, name: string) => {
    await page.getByRole("textbox", { name: "Search by name or code" }).fill(name);
  };
  const result = (page: Page, name: string) =>
    page
      .getByRole("list", { name: "Locations" })
      .getByRole("button", { name: new RegExp(`^${name} `) });

  test.beforeAll(async ({ playwright, baseURL }) => {
    const requestContext = await playwright.request.newContext({ baseURL });
    api = new ApiHelper(requestContext);
    token = (await api.login(ADMIN_EMAIL, ADMIN_PASSWORD)).access_token;
    await api.enableAllModules(token);
  });

  test.afterAll(async () => {
    // Children first: a location with a child moves it up a level on delete.
    for (const id of created.reverse())
      await api.deleteStorage(token, id).catch(() => {});
  });

  test.beforeEach(async ({ page, authenticatedPage }) => {
    void authenticatedPage;
    await page.goto("/inventory/locations");
    await expect(
      page.getByRole("heading", { level: 1, name: "Locations" }),
    ).toBeVisible({ timeout: 15000 });
  });

  test("finds a location in the tree by its name", async ({ page }) => {
    const name = `Z_Test Storage ${uniqueId()}`;
    await makeStorage(name);
    await page.reload();

    await search(page, name);
    await expect(result(page, name)).toBeVisible({ timeout: 15000 });
  });

  test("adds a location and a location inside it via the wizard", async ({
    page,
  }) => {
    const zoneName = `New Zone ${uniqueId()}`;
    const locationName = `Wizard Location ${uniqueId()}`;

    await page.getByRole("button", { name: "Add location", exact: true }).click();
    const wizard = page.getByRole("dialog", { name: "Location Wizard" });
    await expect(wizard).toBeVisible({ timeout: 10000 });

    await wizard.getByRole("textbox", { name: "Type or select" }).fill(zoneName);
    await wizard.getByRole("button", { name: "Next", exact: true }).click();
    await wizard
      .getByRole("textbox", { name: /e\.g\. Shelf A/ })
      .fill(locationName);
    await wizard.getByRole("button", { name: "Done", exact: true }).click();
    await expect(wizard).toBeHidden({ timeout: 10000 });

    // Record what the wizard made before asserting, so a failure still
    // leaves nothing behind.
    const storages = await api.listStorages(token);
    for (const name of [zoneName, locationName]) {
      const id = storages.find((s) => s.name === name)?.id;
      if (id) created.unshift(id);
    }

    // The zone stands at the top, the location inside it.
    await search(page, zoneName);
    await expect(result(page, zoneName)).not.toContainText("›");
    await search(page, locationName);
    await expect(result(page, locationName)).toContainText(
      `${zoneName} › ${locationName}`,
    );
  });

  test("selecting a location opens it with its path and contents", async ({
    page,
  }) => {
    const parent = `Z_Parent ${uniqueId()}`;
    const child = `Z_Child ${uniqueId()}`;
    const parentId = await makeStorage(parent);
    const childId = await makeStorage(child, parentId);
    await page.reload();

    await search(page, child);
    await result(page, child).click();

    await expect(page).toHaveURL(new RegExp(`/inventory/locations/${childId}$`));
    await expect(
      page.getByRole("heading", { level: 2, name: child }),
    ).toBeVisible();
    const path = page.getByRole("navigation", { name: "Location path" });
    await expect(path.getByRole("button", { name: parent })).toBeVisible();
    await expect(page.getByRole("tab", { name: "Contents" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
  });

  test("renames a location in place", async ({ page }) => {
    const name = `Z_Rename ${uniqueId()}`;
    const renamed = `${name} Edited`;
    const id = await makeStorage(name);
    await page.goto(`/inventory/locations/${id}`);

    await page.getByRole("button", { name: "Rename", exact: true }).click();
    await page.getByRole("textbox", { name: "Location name" }).fill(renamed);
    await page.getByRole("button", { name: "Save name" }).click();

    await expect(
      page.getByRole("heading", { level: 2, name: renamed }),
    ).toBeVisible({ timeout: 10000 });
    const stored = (await api.listStorages(token)).find((s) => s.id === id);
    expect(stored?.name).toBe(renamed);
  });

  test("deletes an empty location from its settings", async ({ page }) => {
    const name = `Z_Delete ${uniqueId()}`;
    const id = await makeStorage(name);
    await page.goto(`/inventory/locations/${id}`);

    await page.getByRole("tab", { name: "Settings" }).click();
    await page
      .getByRole("tabpanel", { name: "Settings" })
      .getByRole("button", { name: `Actions for ${name}` })
      .click();
    await page.getByRole("button", { name: "Delete", exact: true }).click();
    const confirm = page.getByRole("alertdialog").or(page.getByRole("dialog"));
    await confirm.last().getByRole("button", { name: "Delete", exact: true }).click();

    await search(page, name);
    await expect(page.getByText("No locations match the search")).toBeVisible({
      timeout: 15000,
    });
    expect((await api.listStorages(token)).some((s) => s.id === id)).toBe(false);
  });
});

test.describe("Storage — extended actions (API)", () => {
  let api: ApiHelper;
  let token: string;
  let storageId: string;

  test.beforeAll(async ({ playwright, baseURL }, testInfo) => {
    const requestContext = await playwright.request.newContext({ baseURL });
    api = new ApiHelper(requestContext);
    const authData = await api.login(ADMIN_EMAIL, ADMIN_PASSWORD);
    token = authData.access_token;

    // The worker index keeps two workers entering this hook in the same
    // millisecond from building one location name.
    const storage = await api.createStorage(token, {
      name: `Z-API-Storage-${Date.now()}-w${testInfo.workerIndex}`,
    });
    storageId = storage.id;
  });

  test.afterAll(async () => {
    if (token && storageId)
      await api.deleteStorage(token, storageId).catch(() => {});
  });

  test("GET /tree returns tree structure", async () => {
    const tree = await api.getStorageTree(token);
    expect(Array.isArray(tree)).toBeTruthy();
    expect(tree.length).toBeGreaterThan(0);
    expect(tree[0].name).toBeTruthy();
  });

  test("GET /{id}/summary returns location summary", async () => {
    const summary = await api.getStorageSummary(token, storageId);
    expect(summary).toBeTruthy();
    expect(summary.id).toBe(storageId);
    expect(summary.name).toBeTruthy();
    expect(typeof summary.items_count).toBe("number");
  });

  test("GET /{id}/breadcrumb returns breadcrumb path", async () => {
    const breadcrumb = await api.getStorageBreadcrumb(token, storageId);
    expect(Array.isArray(breadcrumb)).toBeTruthy();
    expect(breadcrumb.length).toBeGreaterThan(0);
  });
});
