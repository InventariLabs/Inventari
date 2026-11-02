import { type APIRequestContext, type Page } from "@playwright/test";
import { test, expect } from "./fixtures/auth";
import { ApiHelper } from "./helpers/api";
import { ADMIN_EMAIL, ADMIN_PASSWORD } from "./fixtures/credentials";

/**
 * A skipped picking line on a phone.
 *
 * Skipping the last pending line ends the picking session, and the summary
 * that opens does not let the picker out with a line nobody answered for: a
 * skip is put off, not short. Close, Pack and Escape wait for an answer;
 * Undo skip reopens the line; Backorder books it short under Shortage and
 * leaves one draft for the rest; Not sent books it under Other and leaves
 * none. Every test reads the document afterwards through the API, because the
 * promise is in the books, not in the sentence on the sheet.
 */

const PHONE = { width: 390, height: 844 };
const FIRST_LINE = 2;
const SKIPPED_LINE = 2;

interface Dispatch {
  documentId: string;
  shelfId: string;
  picked: string;
  skipped: string;
  pickedTemplate: string;
  skippedTemplate: string;
}

interface Line {
  product_template_id: string | null;
  expected_quantity: string;
  done_quantity: string;
  discrepancy_code: string | null;
}

interface DocumentRead {
  status: string;
  generated_backorder_id: string | null;
  lines: Line[];
}

test.describe("Picking — a skipped line on a phone", () => {
  test.use({ viewport: PHONE, hasTouch: true, isMobile: true });

  let ctx: APIRequestContext;
  let api: ApiHelper;
  let token: string;
  const auth = () => ({ Authorization: `Bearer ${token}` });
  const made: string[] = [];

  test.beforeAll(async ({ playwright, baseURL }) => {
    ctx = await playwright.request.newContext({ baseURL });
    api = new ApiHelper(ctx);
    token = (await api.login(ADMIN_EMAIL, ADMIN_PASSWORD)).access_token;
    await api.enableAllModules(token);
  });

  // Open dispatches and backorder drafts are tasks on Start for every spec
  // that runs after this one; what can still be taken back is taken back.
  test.afterAll(async () => {
    for (const id of made) {
      const read = await ctx.get(`/api/v1/warehouse/documents/${id}`, {
        headers: auth(),
      });
      if (!read.ok()) continue;
      const document = (await read.json()) as DocumentRead;
      if (document.generated_backorder_id)
        made.push(document.generated_backorder_id);
      await api.cancelDocument(token, id).catch(() => {});
      await api.deleteDocument(token, id).catch(() => {});
    }
  });

  /** A confirmed dispatch of two products, five of each on one shelf. */
  async function newDispatch(workerIndex: number): Promise<Dispatch> {
    const uid = `${Date.now().toString(36)}-w${workerIndex}-${Math.random()
      .toString(36)
      .slice(2, 6)}`;
    const shelf = await api.createStorage(token, {
      name: `E2E-Skip-Shelf-${uid}`,
    });
    const partner = await api.createPartner(token, {
      name: `E2E-Skip-Customer-${uid}`,
      type: "CUSTOMER",
    });
    const lines: Array<Record<string, unknown>> = [];
    const names: string[] = [];
    const templates: string[] = [];
    for (const which of ["Picked", "Skipped"]) {
      const name = `E2E-Skip-${which}-${uid}`;
      names.push(name);
      const template = await api.createProductTemplate(token, { name });
      templates.push(template.id);
      const item = await api.createItemForTemplate(token, {
        name,
        template_id: template.id,
        location_id: shelf.id,
        quantity: 5,
      });
      lines.push({
        item_id: item.id,
        product_template_id: template.id,
        expected_quantity: which === "Picked" ? FIRST_LINE : SKIPPED_LINE,
      });
    }
    const doc = await api.createDocument(token, {
      type: "OUT",
      partner_id: partner.id,
      source_location_id: shelf.id,
      lines,
    });
    await api.confirmDocument(token, doc.id);
    made.push(doc.id);
    return {
      documentId: doc.id,
      shelfId: shelf.id,
      picked: names[0],
      skipped: names[1],
      pickedTemplate: templates[0],
      skippedTemplate: templates[1],
    };
  }

  async function readDocument(id: string): Promise<DocumentRead> {
    const response = await ctx.get(`/api/v1/warehouse/documents/${id}`, {
      headers: auth(),
    });
    expect(response.ok(), await response.text()).toBe(true);
    return (await response.json()) as DocumentRead;
  }

  /** The line of a product: the API does not promise the order of lines. */
  const lineOf = (document: DocumentRead, templateId: string): Line => {
    const line = document.lines.find(
      (l) => l.product_template_id === templateId,
    );
    expect(line, `a line for product ${templateId}`).toBeTruthy();
    return line as Line;
  };

  /** The documents that continue `id` — backorder drafts it left. */
  async function backordersOf(id: string): Promise<unknown[]> {
    const response = await ctx.get(
      "/api/v1/warehouse/documents?limit=500&type=OUT",
      { headers: auth() },
    );
    expect(response.ok(), await response.text()).toBe(true);
    const body = await response.json();
    const rows = (Array.isArray(body) ? body : body.items) as Array<{
      backorder_id?: string | null;
    }>;
    return rows.filter((row) => row.backorder_id === id);
  }

  /** Opens the picking sheet of the dispatch, as the picker does. */
  async function openPicking(page: Page, d: Dispatch) {
    await page.goto(`/warehouse/documents/${d.documentId}`);
    await page.getByRole("button", { name: "Scan picking" }).click();
    const sheet = page.getByRole("dialog", { name: "Picking" });
    await expect(sheet).toBeVisible({ timeout: 15000 });
    return sheet;
  }

  /**
   * Pick the first line in full and skip the last one: the session has no
   * pending line left and the summary opens. Where the organisation asks for
   * the shelf to be confirmed by scan, the picker scans it first.
   */
  async function pickOneAndSkipTheLast(page: Page, d: Dispatch) {
    const sheet = await openPicking(page, d);
    const shelfPrompt = sheet.getByText("Scan the location label").first();
    if (await shelfPrompt.isVisible()) {
      const shelf = await ctx.get(`/api/v1/locations/${d.shelfId}`, {
        headers: auth(),
      });
      await sheet
        .getByRole("textbox", { name: "Scan barcode or type…" })
        .fill((await shelf.json()).short_code);
      await sheet.getByRole("button", { name: "Scan", exact: true }).click();
      await expect(shelfPrompt).toBeHidden();
    }
    // The list is ordered by the shelf stock sits on, not by the document, so
    // each line is found by its product.
    const rowOf = (product: string) =>
      sheet
        .locator("div")
        .filter({ has: page.getByText(product, { exact: true }) })
        .filter({ has: page.getByRole("button", { name: "Skip" }) })
        .last();
    await rowOf(d.picked)
      .getByRole("button", { name: "Pick full amount" })
      .click();
    // The first line is done when only the second still offers a skip.
    const skip = sheet.getByRole("button", { name: "Skip", exact: true });
    await expect(skip).toHaveCount(1);
    await rowOf(d.skipped)
      .getByRole("button", { name: "Skip", exact: true })
      .click();
    await page
      .getByRole("alertdialog", { name: "Skip this line?" })
      .getByRole("button", { name: "Skip", exact: true })
      .click();
    return summaryOf(page);
  }

  function summaryOf(page: Page) {
    return page.getByRole("dialog", { name: "Picking Complete" });
  }

  const MUST_ANSWER =
    "Answer every skipped line first: Undo skip, Backorder or Not sent.";

  for (const way of ["Complete and book", "Pack"] as const) {
    test(`${way} on the summary waits for an answer about the skipped line`, async ({
      page,
      authenticatedPage,
    }, testInfo) => {
      void authenticatedPage;
      const d = await newDispatch(testInfo.workerIndex);
      const summary = await pickOneAndSkipTheLast(page, d);
      await expect(summary).toContainText("1 of 2 lines picked");
      await expect(summary).toContainText("1 skipped");

      await summary.getByRole("button", { name: way, exact: true }).click();

      // The sheet says what is missing, and stays.
      await expect(summary.getByRole("alert")).toHaveText(MUST_ANSWER);
      await expect(summary).toBeVisible();
      await expect(
        summary.getByRole("button", { name: "Undo skip" }),
      ).toBeVisible();
      await expect(page).toHaveURL(
        new RegExp(`/warehouse/documents/${d.documentId}$`),
      );

      // Nothing was booked and nothing was left behind.
      const document = await readDocument(d.documentId);
      expect(document.status).toBe("CONFIRMED");
      expect(document.generated_backorder_id).toBeNull();
      expect(await backordersOf(d.documentId)).toHaveLength(0);
    });
  }

  test("Escape leaves the summary without booking, the skip still to answer", async ({
    page,
    authenticatedPage,
  }, testInfo) => {
    // Only the completing button books; leaving the sheet any other way
    // keeps the dispatch confirmed as picked, so there is nothing to refuse.
    void authenticatedPage;
    const d = await newDispatch(testInfo.workerIndex);
    const summary = await pickOneAndSkipTheLast(page, d);
    await expect(summary).toContainText("1 skipped");

    await page.keyboard.press("Escape");

    await expect(summary).toBeHidden();
    const document = await readDocument(d.documentId);
    expect(document.status).toBe("CONFIRMED");
    expect(document.generated_backorder_id).toBeNull();
    expect(await backordersOf(d.documentId)).toHaveLength(0);
  });

  test("Undo skip puts the line back on the list, and picking it finishes the document", async ({
    page,
    authenticatedPage,
  }, testInfo) => {
    void authenticatedPage;
    const d = await newDispatch(testInfo.workerIndex);
    const summary = await pickOneAndSkipTheLast(page, d);

    await summary.getByRole("button", { name: "Undo skip" }).click();

    // The summary is gone and the skipped line is pending again, with the
    // buttons to pick it.
    const sheet = page.getByRole("dialog", { name: "Picking" });
    await expect(sheet).toBeVisible({ timeout: 15000 });
    await expect(summary).toBeHidden();
    await expect(sheet).toContainText(d.skipped);
    await sheet.getByRole("button", { name: "Pick full amount" }).click();

    await expect(summary).toBeVisible({ timeout: 15000 });
    await expect(summary).toContainText("2 of 2 lines picked");
    await expect(summary).not.toContainText("skipped");
    await summary
      .getByRole("button", { name: "Complete and book", exact: true })
      .click();
    await expect(summary).toBeHidden();

    await expect
      .poll(async () => (await readDocument(d.documentId)).status, {
        timeout: 15000,
      })
      .toBe("COMPLETED");
    const document = await readDocument(d.documentId);
    expect(
      [d.pickedTemplate, d.skippedTemplate].map((id) =>
        Number(lineOf(document, id).done_quantity),
      ),
    ).toEqual([FIRST_LINE, SKIPPED_LINE]);
    expect(await backordersOf(d.documentId)).toHaveLength(0);
  });

  test("a reload keeps the question open: picking is resumed on the same summary", async ({
    page,
    authenticatedPage,
  }, testInfo) => {
    void authenticatedPage;
    const d = await newDispatch(testInfo.workerIndex);
    const summary = await pickOneAndSkipTheLast(page, d);
    await expect(summary).toBeVisible();

    await page.reload();
    await page.getByRole("button", { name: "Scan picking" }).click();

    // The same session comes back with the same unanswered line, not a
    // fresh list with the skip forgotten.
    const resumed = summaryOf(page);
    await expect(resumed).toBeVisible({ timeout: 15000 });
    await expect(resumed).toContainText("1 of 2 lines picked");
    await expect(resumed).toContainText("1 skipped");
    await expect(resumed).toContainText(d.skipped);
    await expect(
      resumed.getByRole("button", { name: "Undo skip" }),
    ).toBeVisible();
    await resumed
      .getByRole("button", { name: "Complete and book", exact: true })
      .click();
    await expect(resumed.getByRole("alert")).toHaveText(MUST_ANSWER);
    expect((await readDocument(d.documentId)).status).toBe("CONFIRMED");
  });

  test("Backorder books the line short under Shortage and leaves exactly one draft", async ({
    page,
    authenticatedPage,
  }, testInfo) => {
    void authenticatedPage;
    const d = await newDispatch(testInfo.workerIndex);
    const summary = await pickOneAndSkipTheLast(page, d);

    await summary.getByRole("button", { name: "Backorder" }).click();
    await expect(summary).toContainText("1 short picked");
    await expect(summary).toContainText("Backorder");
    await expect(
      summary.getByRole("button", { name: "Undo skip" }),
    ).toHaveCount(0);

    await summary
      .getByRole("button", { name: "Complete and book", exact: true })
      .click();
    await expect(summary).toBeHidden();

    await expect
      .poll(async () => (await readDocument(d.documentId)).status, {
        timeout: 15000,
      })
      .toBe("COMPLETED");
    const document = await readDocument(d.documentId);
    const skipped = lineOf(document, d.skippedTemplate);
    expect(Number(skipped.done_quantity)).toBe(0);
    expect(skipped.discrepancy_code).toBe("SHORTAGE");
    expect(Number(lineOf(document, d.pickedTemplate).done_quantity)).toBe(
      FIRST_LINE,
    );

    // One draft that continues this document, holding the line that was owed.
    const drafts = await backordersOf(d.documentId);
    expect(drafts).toHaveLength(1);
    expect(document.generated_backorder_id).toBe(
      (drafts[0] as { id: string }).id,
    );
    const draft = await readDocument(document.generated_backorder_id as string);
    expect(draft.status).toBe("DRAFT");
    expect(draft.lines).toHaveLength(1);
    expect(Number(draft.lines[0].expected_quantity)).toBe(SKIPPED_LINE);
  });

  test("Not sent books the line under Other and leaves no draft", async ({
    page,
    authenticatedPage,
  }, testInfo) => {
    void authenticatedPage;
    const d = await newDispatch(testInfo.workerIndex);
    const summary = await pickOneAndSkipTheLast(page, d);

    await summary.getByRole("button", { name: "Not sent" }).click();
    await expect(summary).toContainText("1 short picked");
    await expect(summary).toContainText("Not sent");

    await summary
      .getByRole("button", { name: "Complete and book", exact: true })
      .click();
    await expect(summary).toBeHidden();

    await expect
      .poll(async () => (await readDocument(d.documentId)).status, {
        timeout: 15000,
      })
      .toBe("COMPLETED");
    const document = await readDocument(d.documentId);
    const skipped = lineOf(document, d.skippedTemplate);
    expect(Number(skipped.done_quantity)).toBe(0);
    expect(skipped.discrepancy_code).toBe("OTHER");
    expect(document.generated_backorder_id).toBeNull();
    expect(await backordersOf(d.documentId)).toHaveLength(0);
  });
});
