import { test, expect } from "./fixtures/auth";
import { startSeed, type ReceivingSeed } from "./helpers/receive-seed";

/**
 * Goods at a reduced rate next to goods at the standard one, from the
 * Settings screen to the totals of a receipt — and the partner tax-ID rule a
 * country gives a profile that states none, which Settings shows and
 * confirmation enforces.
 *
 * The pieces each have a component test; this walks the wiring between them:
 * the country's rates saved from Settings, a category that names one, a new
 * line that takes it without anyone typing a rate, a rate with decimals
 * edited on a line, and the tax per rate under the totals.
 *
 * The rates table, the profile and the organization's country are
 * organization-wide, so the spec runs in the one-worker `value-tracking`
 * project and puts what it changed back.
 */

const PROFILE = "/api/v1/warehouse/profile";
const RATES = "/api/v1/warehouse/tax-rates";

interface Saved {
  country: string | null;
  profile: Record<string, unknown>;
  rateIds: Set<string>;
}

let saved: Saved | undefined;
let seeded: ReceivingSeed | undefined;

function auth(seed: ReceivingSeed) {
  return { Authorization: `Bearer ${seed.token}` };
}

/** The body of an answer that must be a success. */
async function body<T>(
  answer: Promise<{
    ok(): boolean;
    text(): Promise<string>;
    json(): Promise<unknown>;
  }>,
): Promise<T> {
  const response = await answer;
  if (!response.ok()) throw new Error(await response.text());
  return (await response.json()) as T;
}

async function readRateIds(seed: ReceivingSeed): Promise<Set<string>> {
  const page = await body<{ items: Array<{ id: string }> }>(
    seed.request.get(RATES, { headers: auth(seed) }),
  );
  return new Set(page.items.map((r) => r.id));
}

/** The organization in France, on a full-value profile with a rate per line. */
async function setUp(seed: ReceivingSeed): Promise<void> {
  const headers = auth(seed);
  const org = await body<{ country: string | null }>(
    seed.request.get("/api/v1/organizations/my", { headers }),
  );
  saved = {
    country: org.country,
    profile: await body(seed.request.get(PROFILE, { headers })),
    rateIds: await readRateIds(seed),
  };
  await body(
    seed.request.put("/api/v1/organizations", {
      headers,
      data: { country: "FR" },
    }),
  );
  await body(
    seed.request.put(PROFILE, {
      headers,
      data: {
        value_tracking_enabled: true,
        tax_handling: "PER_LINE_RATE",
        default_tax_rate: "20",
        // No entry of its own: the country answers.
        require_partner_tax_id: null,
      },
    }),
  );
}

/** Put the country, the profile and the rates table back as they were. */
async function putBack(seed: ReceivingSeed): Promise<void> {
  if (!saved) return;
  const headers = auth(seed);
  const profile = saved.profile;
  await seed.request.put(PROFILE, {
    headers,
    data: {
      value_tracking_enabled: profile.value_tracking_enabled,
      tax_handling: profile.tax_handling,
      default_tax_rate: profile.default_tax_rate ?? null,
      require_partner_tax_id: profile.require_partner_tax_id ?? null,
    },
  });
  await seed.request.put("/api/v1/organizations", {
    headers,
    data: { country: saved.country },
  });
  const added = [...(await readRateIds(seed))].filter(
    (id) => !saved?.rateIds.has(id),
  );
  // A rate a category still names cannot go: let the categories go first.
  const named = await body<{
    items: Array<{ category_id: string; tax_rate_id: string }>;
  }>(seed.request.get(`${RATES}/categories`, { headers }));
  for (const row of named.items.filter((r) => added.includes(r.tax_rate_id))) {
    await seed.request.put(`${RATES}/categories/${row.category_id}`, {
      headers,
      data: { tax_rate_id: null },
    });
  }
  for (const id of added) {
    await seed.request.delete(`${RATES}/${id}`, { headers });
  }
}

// A timed-out test never reaches a `finally`, so the put-back is a hook.
test.afterEach(async () => {
  if (seeded) await putBack(seeded);
  seeded = undefined;
  saved = undefined;
});

test("reduced rates run from Settings to the per-rate totals of a receipt", async ({
  page,
  playwright,
  baseURL,
  authenticatedPage: _auth,
}, testInfo) => {
  test.setTimeout(60_000);
  const seed = await startSeed({ playwright }, baseURL, testInfo);
  seeded = seed;
  await setUp(seed);

  const shelf = await seed.shelf("Shelf");
  const foodName = `E2E-Rates-Food-${seed.uid}`;
  const food = await seed.api.createCategory(seed.token, { name: foodName });
  // A product with records filed under the category, and one with none.
  const milk = `E2E-Rates-Milk-${seed.uid}`;
  await seed.api.createItem(seed.token, {
    name: milk,
    quantity: 1,
    location_id: shelf.id,
    category_id: food.id,
  });
  const hammer = await seed.product("Hammer");

  // ---- Settings: the country's rates, then a category naming one ----
  await page.goto("/warehouse/settings");
  await page.getByRole("tab", { name: "Numbering and prices" }).click();
  // The rates are written with their own digits: 5.5% and 2.1%, not 6% and 2%.
  const addCountry = page.getByRole("button", {
    name: "Add the country's rates: 20%, 10%, 5.5%, 2.1%",
  });
  await addCountry.click();
  await expect(addCountry).toHaveCount(0);
  await page.getByRole("button", { name: "Add a category" }).click();
  await page
    .getByLabel("Category", { exact: true })
    .selectOption({ label: foodName });
  const rateChoice = page.getByLabel("Rate", { exact: true }).last();
  await rateChoice.selectOption({ label: "TVA 5.5%" });
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await expect(page.getByText("You have unsaved changes")).toHaveCount(0);

  // What was saved, read back: the country's four rates, and the category
  // naming the one with decimals.
  const rates = await body<{ items: Array<{ id: string; rate: string }> }>(
    seed.request.get(RATES, { headers: auth(seed) }),
  );
  const reduced = rates.items.find((r) => Number(r.rate) === 5.5);
  expect(reduced).toBeTruthy();
  const assigned = await body<{
    items: Array<{ category_id: string; tax_rate_id: string }>;
  }>(seed.request.get(`${RATES}/categories`, { headers: auth(seed) }));
  expect(assigned.items).toContainEqual({
    category_id: food.id,
    tax_rate_id: reduced?.id,
  });

  // ---- A receipt: the lines take the rates, no one types one ----
  const supplier = await seed.partner("Supplier", "SUPPLIER");
  await page.goto("/warehouse/all");
  await page
    .getByRole("button", { name: "New document", exact: true })
    .click({ timeout: 15000 });
  await page
    .getByRole("menu", { name: "New document" })
    .getByRole("menuitem", { name: /^Receipt\b/ })
    .click();
  const form = page.getByRole("dialog", { name: "New document" });
  await expect(form).toBeVisible();
  await form.getByRole("combobox", { name: /partner/i }).click();
  await page.getByRole("button", { name: supplier.name, exact: true }).click();
  await form.getByRole("combobox", { name: /to location/i }).click();
  await page.getByRole("button", { name: shelf.name, exact: true }).click();

  const addLine = async (index: number, name: string, price: string) => {
    if (index > 0) await form.getByRole("button", { name: "Add line" }).click();
    // A line with a product has no picker; the empty one is always last.
    await form.getByRole("combobox", { name: "Item" }).last().fill(name);
    await page.getByRole("option", { name }).first().click();
    await form
      .getByRole("spinbutton", { name: "Unit price" })
      .nth(index)
      .fill(price);
  };
  await addLine(0, milk, "2");
  await form.getByRole("spinbutton", { name: "Quantity" }).nth(0).fill("10");
  await addLine(1, hammer.name, "10");
  const rateField = (index: number) =>
    form.getByRole("spinbutton", { name: "VAT %" }).nth(index);
  // The milk takes its category's rate, the hammer the profile's default.
  await expect(rateField(0)).toHaveValue("5.50");
  await expect(rateField(1)).toHaveValue("20.00");

  // The hammer is taxed at 2.1% on this one receipt: a rate with decimals,
  // edited on the line, is kept as typed.
  await rateField(1).fill("2.1");
  await expect(rateField(1)).toHaveValue("2.1");
  await form.getByRole("button", { name: "Create receipt" }).click();
  await expect(form).toBeHidden();

  // ---- The receipt: the tax per rate under the totals ----
  const [receipt] = await seed.api.listDocuments(
    seed.token,
    `partner_id=${supplier.id}`,
  );
  expect(receipt).toBeTruthy();
  await page.goto(`/warehouse/documents/${receipt.id}`);
  await expect(page.getByText("$31.31")).toBeVisible();
  const byRate = page.getByRole("table", { name: "Tax by rate" });
  await expect(byRate).toBeVisible();
  // Each rate under its own digits. Fails with the labels the screen used
  // to print — "6%" and "2%" — which round 5.5 and 2.1 to whole numbers.
  await expect(byRate.getByRole("rowheader")).toHaveText(["5.5%", "2.1%"]);
  const milkRow = byRate.getByRole("row", { name: /^5\.5%/ });
  const hammerRow = byRate.getByRole("row", { name: /^2\.1%/ });
  await expect(milkRow).toContainText("20.00");
  await expect(milkRow).toContainText("1.10");
  await expect(hammerRow).toContainText("10.00");
  await expect(hammerRow).toContainText("0.21");
});

test("Settings shows the tax-ID rule confirmation applies, inherited or set", async ({
  page,
  playwright,
  baseURL,
  authenticatedPage: _auth,
}, testInfo) => {
  test.setTimeout(60_000);
  const seed = await startSeed({ playwright }, baseURL, testInfo);
  seeded = seed;
  await setUp(seed);

  const shelf = await seed.shelf("Shelf");
  const hammer = await seed.product("Hammer");
  // A supplier with no tax ID, and a draft receipt from it.
  const supplier = await seed.partner("Supplier", "SUPPLIER");
  const receipt = await seed.api.createDocument(seed.token, {
    type: "IN",
    partner_id: supplier.id,
    target_location_id: shelf.id,
    lines: [
      { product_template_id: hammer.id, expected_quantity: 1, unit_price: "5" },
    ],
  });
  const confirm = () =>
    seed.request.patch(`/api/v1/warehouse/documents/${receipt.id}/confirm`, {
      headers: auth(seed),
    });
  const requirement = page.getByRole("checkbox", {
    name: /require partner tax id/i,
  });
  const source = page.getByTestId("tax-id-source");
  const openSettings = async () => {
    await page.goto("/warehouse/settings");
    await page.getByRole("tab", { name: "Numbering and prices" }).click();
  };

  // No entry on the profile, France asks for the ID: the box is checked and
  // says where that comes from — and confirmation refuses.
  await openSettings();
  await expect(requirement).toBeChecked();
  await expect(source).toContainText("Following the country (FR)");
  const refused = await confirm();
  expect(refused.status()).toBeGreaterThanOrEqual(400);
  expect(await refused.text()).toContain("DOCUMENT_PARTNER_TAX_ID_REQUIRED");

  // An entry of the profile's own beats the country, both ways.
  await requirement.uncheck();
  await expect(source).toContainText("Set for this profile");
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await expect(page.getByText("You have unsaved changes")).toHaveCount(0);
  await openSettings();
  await expect(requirement).not.toBeChecked();
  await expect(source).toContainText("Set for this profile");
  const saved = await body<{ require_partner_tax_id: boolean | null }>(
    seed.request.get(PROFILE, { headers: auth(seed) }),
  );
  expect(saved.require_partner_tax_id).toBe(false);
  expect((await confirm()).ok()).toBe(true);

  // Following the country again clears the entry: null on the profile and
  // the country's rule on the screen.
  await page.getByRole("button", { name: "Follow the country again" }).click();
  await expect(requirement).toBeChecked();
  await expect(source).toContainText("Following the country (FR)");
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await expect(page.getByText("You have unsaved changes")).toHaveCount(0);
  const cleared = await body<{ require_partner_tax_id: boolean | null }>(
    seed.request.get(PROFILE, { headers: auth(seed) }),
  );
  expect(cleared.require_partner_tax_id).toBeNull();
});
