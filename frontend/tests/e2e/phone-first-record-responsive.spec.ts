import type { Page, Locator } from "@playwright/test";
import { test } from "./fixtures/auth";
import { ApiHelper } from "./helpers/api";
import { ADMIN_EMAIL, ADMIN_PASSWORD } from "./fixtures/credentials";
import {
  PHONE_HEIGHT,
  PHONE_WIDTH,
  expectFirstRecordAboveFold,
} from "./helpers/phone-first-record";

/**
 * A list opened on a phone must show a record, not only its controls.
 *
 * A needs-attention link from the Inventory overview used to land on a full
 * screen of search, tabs, sort, seven wrapped chips and an open Place/Category
 * panel, with the first product below the fold: a reader who followed a link
 * promising the products that need attention saw none of them. JSDOM has no
 * layout, so only a real browser at a real viewport can say where the first
 * record starts.
 *
 * Every list reached from the main navigation and from the overview cards is
 * opened at 360x800 (a small Android phone), and its first record has to start
 * above the fold: clear of the bottom navigation, with room left to read it.
 */

/**
 * The first record of a list, found by the structure of the screen — never by
 * what the seed wrote. A shared organization holds other rows too, and the
 * record a person meets first is whichever the list puts on top; the seed only
 * guarantees that there is one.
 */
type RecordOf = (page: Page) => Locator;

interface ListRoute {
  name: string;
  path: string;
  record: RecordOf;
  /** A step a person takes before the records appear. */
  open?: (page: Page, tag: string) => Promise<void>;
}

const testid =
  (id: string): RecordOf =>
  (page) =>
    page.locator(`[data-testid=${id}]`).first();
const css =
  (selector: string): RecordOf =>
  (page) =>
    page.locator(selector).first();
/** A document number such as INT/2026/004, or MM/2026/11/0006 when the format carries the month. */
const documentNumber: RecordOf = (page) =>
  page.getByText(/^[A-Z]+\/\d{4}(?:\/\d{2})?\/\d+$/).first();

// Every list of the main navigation and of the overview cards. The
// approvals screens need a workflow that holds every document of the
// organization while it exists, so they run in their own project
// (`phone-approvals.spec.ts`).
const ROUTES: ListRoute[] = [
  // Inventory: the overview cards and the navigation.
  { name: "products", path: "/inventory/items", record: testid("item-row") },
  {
    name: "products needing attention",
    path: "/inventory/items?filter=needs-attention",
    record: testid("item-row"),
  },
  {
    name: "products running low",
    path: "/inventory/items?filter=low-stock",
    record: testid("item-row"),
  },
  {
    name: "products expiring",
    path: "/inventory/items?filter=expiring",
    record: testid("item-row"),
  },
  {
    name: "products expired",
    path: "/inventory/items?filter=expired",
    record: testid("item-row"),
  },
  { name: "places", path: "/inventory/locations", record: css("main ul > li") },
  { name: "stock", path: "/inventory/stock", record: css("main ul > li") },
  {
    name: "stock movements",
    path: "/inventory/moves",
    record: css("main ul > li"),
  },
  {
    name: "stock takes",
    path: "/inventory/stock-takes",
    record: css('main a[href^="/inventory/stock-takes/"]'),
  },
  { name: "labels", path: "/inventory/labels", record: testid("label-row") },
  {
    name: "categories",
    path: "/inventory/categories",
    record: css('main a[href*="category_id="]'),
  },
  {
    name: "archived products",
    path: "/inventory/items/archived",
    record: css("main tbody tr"),
  },
  // Warehouse.
  {
    name: "warehouse start",
    path: "/warehouse/todo",
    record: testid("work-item"),
  },
  {
    name: "warehouse board",
    path: "/warehouse/board",
    record: testid("work-item"),
  },
  {
    name: "warehouse history",
    path: "/warehouse/history",
    record: css("main li"),
  },
  {
    name: "warehouse documents",
    path: "/warehouse/all",
    record: documentNumber,
  },
  {
    name: "warehouse codes and labels",
    path: "/warehouse/location-settings",
    record: css("main ul > li"),
  },
  {
    name: "warehouse occupancy",
    path: "/warehouse/occupancy",
    record: css("main ul > li"),
  },
  {
    name: "warehouse putaway rules",
    path: "/warehouse/putaway-rules",
    record: css("main tbody tr"),
  },
  {
    name: "warehouse document templates",
    path: "/warehouse/templates",
    record: testid("template-card"),
  },
  // Equipment.
  {
    name: "equipment",
    path: "/equipment/assets",
    record: testid("asset-card"),
  },
  { name: "my equipment", path: "/equipment/my", record: css("main h4") },
  {
    name: "equipment locations",
    path: "/equipment/locations",
    record: css('main a[href*="/equipment/assets?location="]'),
  },
  {
    name: "equipment categories",
    path: "/equipment/categories",
    record: css("main ul > li"),
  },
  {
    name: "equipment document templates",
    path: "/equipment/templates",
    record: testid("template-card"),
  },
  {
    name: "equipment models",
    path: "/equipment/templates",
    open: (page) => page.getByRole("tab", { name: "Equipment Models" }).click(),
    record: testid("model-card"),
  },
  {
    name: "equipment attestations",
    path: "/equipment/campaigns",
    record: css('main a[href^="/equipment/campaigns/"]'),
  },
  // Partners, recipes, shopping lists, purchase orders, production.
  { name: "partners", path: "/partners", record: testid("partner-card") },
  { name: "recipes", path: "/recipes", record: testid("recipe-card") },
  {
    name: "ingredients to link",
    path: "/recipes/unlinked-ingredients",
    record: css("main tbody tr"),
  },
  {
    name: "meal planner",
    path: "/recipes/meal-planner",
    record: css("main h3"),
  },
  {
    name: "shopping lists",
    path: "/shopping-lists",
    record: testid("shopping-list-card"),
  },
  {
    name: "purchase orders",
    path: "/purchase-orders",
    record: testid("purchase-order-card"),
  },
  {
    name: "purchase order templates",
    path: "/purchase-orders/templates",
    record: testid("template-card"),
  },
  {
    // The list is the supplier's: its records appear once one is chosen.
    name: "supplier prices",
    path: "/purchase-orders/pricelist",
    open: async (page, tag) => {
      await page.locator("#pricelist-supplier").click();
      await page.getByPlaceholder("Search suppliers…").fill(`${tag} partner`);
      await page.getByRole("button", { name: `${tag} partner` }).click();
    },
    record: css("main tbody tr"),
  },
  {
    // Alerts above the rules are records too: whichever comes first.
    name: "reorder rules",
    path: "/purchase-orders/reorder-rules",
    record: css("main li, main tbody tr"),
  },
  {
    name: "recipe catalogue",
    path: "/maker",
    record: testid("maker-recipe-card"),
  },
  {
    name: "production",
    path: "/maker/production",
    record: testid("maker-order-number"),
  },
];

test.describe("Phone lists — the first record is above the fold", () => {
  // One worker for the whole file: the rows are seeded once, not once per
  // worker.
  test.describe.configure({ mode: "default" });

  let api: ApiHelper;
  let token: string;
  let tag: string;
  const cleanup: (() => Promise<unknown>)[] = [];

  test.beforeAll(async ({ playwright, baseURL }, workerInfo) => {
    cleanup.length = 0;
    const requestContext = await playwright.request.newContext({ baseURL });
    api = new ApiHelper(requestContext);
    token = (await api.login(ADMIN_EMAIL, ADMIN_PASSWORD)).access_token;
    await api.enableAllModules(token);

    // Other specs share the organization; the stamp keeps these rows apart.
    tag = `Phone1st-${workerInfo.project.name}-${Date.now()}-w${workerInfo.workerIndex}`;
    const storage = await api.createStorage(token, { name: `${tag} place` });
    cleanup.push(() => api.deleteStorage(token, storage.id));

    // Expired yesterday: the list that "needs attention" has a row.
    const yesterday = new Date(Date.now() - 86_400_000)
      .toISOString()
      .slice(0, 10);
    for (const name of [`${tag} milk`, `${tag} bread`]) {
      const item = await api.createItem(token, {
        name,
        quantity: 1,
        location_id: storage.id,
        expiry_date: yesterday,
      });
      cleanup.push(() => api.deleteItem(token, item.id));
    }

    // Running low: below the minimum the product asks for. Expiring: a few
    // days left.
    const low = await api.createItem(token, {
      name: `${tag} salt`,
      quantity: 1,
      min_quantity: 5,
      location_id: storage.id,
    });
    cleanup.push(() => api.deleteItem(token, low.id));
    const soon = await api.createItem(token, {
      name: `${tag} yoghurt`,
      quantity: 1,
      location_id: storage.id,
      expiry_date: new Date(Date.now() + 3 * 86_400_000)
        .toISOString()
        .slice(0, 10),
    });
    cleanup.push(() => api.deleteItem(token, soon.id));

    const partner = await api.createPartner(token, {
      name: `${tag} partner`,
      type: "supplier",
    });
    cleanup.push(() => api.deletePartner(token, partner.id));

    const order = await api.createPurchaseOrder(token, {
      number: `${tag}-PO`,
      partner_id: partner.id,
      status: "DRAFT",
      lines: [{ name: `${tag} line`, quantity_ordered: 1, unit_price: "1.00" }],
    });
    cleanup.push(() => api.cancelPurchaseOrder(token, order.id));

    const list = await api.createShoppingList(token, { name: `${tag} list` });
    cleanup.push(() => api.deleteShoppingList(token, list.id));

    // One free-text ingredient: no product behind it, so it is listed
    // among the ingredients still to link.
    const recipe = await api.createRecipe(token, {
      name: `${tag} recipe`,
      servings: 2,
      ingredients: [{ name: `${tag} flour`, quantity: 1 }],
    });
    cleanup.push(() => api.deleteRecipe(token, recipe.id));

    const category = await api.createCategoryIdempotent(token, {
      name: `E2E-Phone1st-${workerInfo.project.name}`,
      context_tag: "equipment",
    });
    const asset = await api.createEquipmentItem(token, {
      name: `${tag} laptop`,
      quantity: 1,
      location_id: storage.id,
      category_id: category.id,
      metadata: { equipment: { equipment_status: "AVAILABLE" } },
    });
    cleanup.push(() => api.deleteItem(token, asset.id));
    await api.checkoutAsset(token, {
      item_id: asset.id,
      assigned_to_name: "Admin",
      assigned_to_email: ADMIN_EMAIL,
    });
    const model = await api.createModel(token, { name: `${tag} model` });
    cleanup.push(() => api.deleteModel(token, model.id));
    const campaign = await api.createCampaign(token, {
      name: `${tag} audit`,
      deadline: new Date(Date.now() + 7 * 86_400_000).toISOString(),
    });
    cleanup.push(() => api.deleteCampaign(token, campaign.id));

    // The warehouse desk: one transfer waiting (Start, Board), one
    // confirmed (History).
    const other = await api.createStorage(token, { name: `${tag} shelf` });
    cleanup.push(() => api.deleteStorage(token, other.id));
    const transfer = (n: number) =>
      api.createIntDocumentWithStock(token, {
        source_location_id: storage.id,
        target_location_id: other.id,
        lines: [{ name: `${tag} transfer ${n}`, expected_quantity: 1 }],
      });
    const waiting = await transfer(1);
    cleanup.push(() => api.deleteDocument(token, waiting.id));
    // Confirmed and not executed: the transfer is a task on the desk.
    await api.confirmDocument(token, waiting.id);
    const done = await transfer(2);
    cleanup.push(() => api.deleteDocument(token, done.id));
    await api.confirmDocument(token, done.id);
    await api.completeDocument(token, done.id);

    // Lists of the inventory navigation.
    const take = await api.createStockTake(token, {
      name: `${tag} count`,
      location_id: storage.id,
    });
    cleanup.push(() => api.deleteStockTake(token, take.id));
    for (const label of await api.generateLabels(token, 2, "P1")) {
      cleanup.push(() => api.deleteLabel(token, label.id));
    }
    const archived = await api.createItem(token, {
      name: `${tag} archived`,
      quantity: 1,
      location_id: storage.id,
    });
    await api.deleteItem(token, archived.id);

    // A production order needs a formula for its output product.
    const parent = await api.createProductTemplate(token, {
      name: `${tag} cake`,
    });
    await api.createMakerRecipe(token, {
      output_template_id: parent.id,
      name: `${tag} formula`,
      reference_price: "12.50",
    });
    const run = await api.createProductionOrder(token, {
      output_template_id: parent.id,
      planned_qty: 3,
      output_location_id: storage.id,
    });
    cleanup.push(() => api.cancelProductionOrder(token, run.id));
    // A run closed this month gives the catalogue its result widget, which is
    // what sits above the recipes on a phone when it is not moved below them.
    const fruit = await api.createProductTemplate(token, {
      name: `${tag} fruit`,
    });
    await api.seedStock(token, {
      product_template_id: fruit.id,
      product_template_name: `${tag} fruit`,
      location_id: storage.id,
      quantity: 5,
    });
    await api.createBomLine(token, {
      parent_template_id: parent.id,
      child_template_id: fruit.id,
      qty_per_batch: "1",
      unit: "kg",
    });
    const closed = await api.createProductionOrder(token, {
      output_template_id: parent.id,
      planned_qty: 1,
      output_location_id: storage.id,
    });
    await api.completeProductionOrder(token, closed.id);

    // Rules and prices of the warehouse and purchase-order screens, on the
    // same product.
    const putaway = await api.postJson(
      token,
      "/api/v1/warehouse/putaway-rules",
      {
        product_template_id: parent.id,
        target_location_id: other.id,
      },
    );
    cleanup.push(() =>
      api.deletePath(token, `/api/v1/warehouse/putaway-rules/${putaway.id}`),
    );
    const reorder = await api.postJson(
      token,
      "/api/v1/purchase-orders/reorder-rules",
      {
        product_template_id: parent.id,
        location_id: storage.id,
        min_quantity: 2,
        max_quantity: 10,
      },
    );
    cleanup.push(() =>
      api.deletePath(
        token,
        `/api/v1/purchase-orders/reorder-rules/${reorder.id}`,
      ),
    );
    const price = await api.postJson(
      token,
      "/api/v1/purchase-orders/pricelist",
      {
        partner_id: partner.id,
        product_template_id: parent.id,
        unit_price: "2.50",
        currency: "USD",
        valid_from: new Date().toISOString().slice(0, 10),
      },
    );
    cleanup.push(() =>
      api.deletePath(token, `/api/v1/purchase-orders/pricelist/${price.id}`),
    );

    // A meal plan, and the built-in document templates of the three modules
    // that keep them (the organization starts with none).
    const plan = await api.createMealPlan(token, {
      name: `${tag} plan`,
      start_date: new Date().toISOString().slice(0, 10),
      end_date: new Date(Date.now() + 6 * 86_400_000)
        .toISOString()
        .slice(0, 10),
      enabled_slots: ["LUNCH"],
    });
    cleanup.push(() => api.deleteMealPlan(token, plan.id));
    for (const module of ["warehouse", "purchase-orders", "equipment"]) {
      const created = await api.postJson<{ id: string }[]>(
        token,
        `/api/v1/${module}/templates/seed-defaults`,
      );
      for (const template of created) {
        cleanup.push(() =>
          api.deletePath(token, `/api/v1/${module}/templates/${template.id}`),
        );
      }
    }
  });

  test.afterAll(async () => {
    // Last created, first removed: the storage goes after what lies in it.
    for (const undo of cleanup.reverse()) await undo().catch(() => {});
  });

  test.beforeEach(async ({ page, authenticatedPage }) => {
    await page.setViewportSize({ width: PHONE_WIDTH, height: PHONE_HEIGHT });
  });

  for (const route of ROUTES) {
    test(`${route.name}: the first record starts above the fold`, async ({
      page,
    }) => {
      await page.goto(route.path);
      await route.open?.(page, tag);
      await expectFirstRecordAboveFold(route.path, route.record(page));
    });
  }
});
