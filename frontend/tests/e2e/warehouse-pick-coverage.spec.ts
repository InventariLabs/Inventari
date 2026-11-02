import { type APIRequestContext, type Page } from "@playwright/test";
import { test, expect } from "./fixtures/auth";
import { ApiHelper } from "./helpers/api";
import { ADMIN_EMAIL, ADMIN_PASSWORD } from "./fixtures/credentials";

/**
 * What stock cannot cover is named before a pick walk starts.
 *
 * A dispatch whose shelf holds less than it orders opens a sheet naming the
 * product, what was ordered and what is there. With nothing short the walk
 * starts at once; with one dispatch short beside a covered one, the person
 * may start without the short one or with both anyway. A session already
 * open over the selection is not a start: Pick hands it back whole, and the
 * gate does not offer a choice the resume could not keep. Every test reads
 * the sessions afterwards through the API, because what was started is in
 * the books, not in the sentence on the sheet.
 */

const SHEET = "Picking";
const GATE = "Stock does not cover every dispatch";
const LEAVE_OUT = "Start without these documents";
const START_ANYWAY = "Start anyway";

interface Dispatch {
  documentId: string;
  number: string;
  product: string;
}

interface SessionRead {
  status: string;
  documents: Array<{ document_id: string }>;
}

test.describe("Picking — the coverage gate before a walk", () => {
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

  // Open sessions and confirmed dispatches are tasks on Start for every spec
  // that runs after this one: each session is cancelled, then its documents.
  test.afterAll(async () => {
    for (const id of made) {
      for (const session of await sessionsOf(id)) {
        if (!["active", "paused"].includes(session.status)) continue;
        await ctx
          .post(
            `/api/v1/warehouse/documents/${id}/picking/${(session as { id: string }).id}/cancel`,
            { headers: auth() },
          )
          .catch(() => {});
      }
      await api.cancelDocument(token, id).catch(() => {});
      await api.deleteDocument(token, id).catch(() => {});
    }
  });

  function uid(workerIndex: number) {
    return `${Date.now().toString(36)}-w${workerIndex}-${Math.random()
      .toString(36)
      .slice(2, 6)}`;
  }

  /**
   * A confirmed dispatch of `ordered` units of one product, from a warehouse
   * of its own. Covered, the units sit on its floor. Short, they wait in its
   * receiving area for putaway: confirmation reserves them all the same, but
   * a picker cannot take them, and nothing on the floor covers the order.
   */
  async function newDispatch(
    partnerId: string,
    tag: string,
    ordered: number,
    short: boolean,
  ): Promise<Dispatch> {
    const warehouse = await api.createStorage(token, {
      name: `E2E-Cover-Warehouse-${tag}`,
    });
    let stockAt = warehouse.id;
    if (short) {
      const mode = await ctx.put(
        `/api/v1/warehouse/putaway/receiving-modes/${warehouse.id}`,
        { headers: auth(), data: { two_step: true } },
      );
      expect(mode.ok(), await mode.text()).toBe(true);
      stockAt = ((await mode.json()) as { receiving_location_id: string })
        .receiving_location_id;
    }
    const product = `E2E-Cover-${tag}`;
    const template = await api.createProductTemplate(token, { name: product });
    const item = await api.createItemForTemplate(token, {
      name: product,
      template_id: template.id,
      location_id: stockAt,
      quantity: ordered,
    });
    const doc = await api.createDocument(token, {
      type: "OUT",
      partner_id: partnerId,
      source_location_id: warehouse.id,
      lines: [
        {
          item_id: item.id,
          product_template_id: template.id,
          expected_quantity: ordered,
        },
      ],
    });
    // A draft's number is provisional: the confirmed one is what lists show.
    const confirmed = (await api.confirmDocument(token, doc.id)) as {
      number: string;
    };
    made.push(doc.id);
    return { documentId: doc.id, number: confirmed.number, product };
  }

  async function sessionsOf(id: string): Promise<SessionRead[]> {
    const response = await ctx.get(
      `/api/v1/warehouse/documents/${id}/picking`,
      { headers: auth() },
    );
    if (!response.ok()) return [];
    return ((await response.json()) as { items: SessionRead[] }).items;
  }

  /** The documents of the one open session over `id`. */
  async function openSessionOver(id: string): Promise<string[]> {
    const open = (await sessionsOf(id)).filter((s) =>
      ["active", "paused"].includes(s.status),
    );
    expect(open, `one open session over ${id}`).toHaveLength(1);
    return open[0].documents.map((d) => d.document_id).sort();
  }

  /** The customer's dispatches on the register, ticked and picked together. */
  async function pickTogether(page: Page, partnerId: string, ds: Dispatch[]) {
    await page.goto(`/warehouse/all?partner_id=${partnerId}`);
    for (const d of ds) {
      await page.getByRole("checkbox", { name: `Select ${d.number}` }).check();
    }
    await page
      .getByRole("button", { name: `Pick ${ds.length} selected` })
      .click();
  }

  test("nothing short: the walk starts without a question", async ({
    page,
    authenticatedPage,
  }, testInfo) => {
    void authenticatedPage;
    const tag = uid(testInfo.workerIndex);
    const partner = await api.createPartner(token, {
      name: `E2E-Cover-Customer-${tag}`,
      type: "CUSTOMER",
    });
    const d = await newDispatch(partner.id, `Full-${tag}`, 3, false);

    await page.goto(`/warehouse/documents/${d.documentId}`);
    await page.getByRole("button", { name: "Scan picking" }).click();

    const sheet = page.getByRole("dialog", { name: SHEET });
    await expect(sheet).toBeVisible({ timeout: 15000 });
    await expect(sheet).toContainText(d.product);
    await expect(page.getByRole("dialog", { name: GATE })).toHaveCount(0);
    expect(await openSessionOver(d.documentId)).toEqual([d.documentId]);
  });

  test("a short dispatch is named with what was ordered and what is there", async ({
    page,
    authenticatedPage,
  }, testInfo) => {
    void authenticatedPage;
    const tag = uid(testInfo.workerIndex);
    const partner = await api.createPartner(token, {
      name: `E2E-Cover-Customer-${tag}`,
      type: "CUSTOMER",
    });
    const d = await newDispatch(partner.id, `Short-${tag}`, 4, true);

    await page.goto(`/warehouse/documents/${d.documentId}`);
    await page.getByRole("button", { name: "Scan picking" }).click();

    const gate = page.getByRole("dialog", { name: GATE });
    await expect(gate).toBeVisible({ timeout: 15000 });
    await expect(gate).toContainText(d.number);
    await expect(gate).toContainText(
      new RegExp(`${d.product} — ordered 4\\b.*, available 0\\b`),
    );
    // Alone, the short dispatch can only be started anyway: leaving it out
    // would leave nothing to pick.
    await expect(gate.getByRole("button", { name: LEAVE_OUT })).toHaveCount(0);
    expect(await sessionsOf(d.documentId)).toHaveLength(0);

    await gate.getByRole("button", { name: START_ANYWAY }).click();
    await expect(page.getByRole("dialog", { name: SHEET })).toBeVisible({
      timeout: 15000,
    });
    expect(await openSessionOver(d.documentId)).toEqual([d.documentId]);
  });

  test("leaving the short dispatch out starts a session over the covered one only", async ({
    page,
    authenticatedPage,
  }, testInfo) => {
    void authenticatedPage;
    const tag = uid(testInfo.workerIndex);
    const partner = await api.createPartner(token, {
      name: `E2E-Cover-Customer-${tag}`,
      type: "CUSTOMER",
    });
    const covered = await newDispatch(partner.id, `Full-${tag}`, 2, false);
    const short = await newDispatch(partner.id, `Short-${tag}`, 4, true);

    await pickTogether(page, partner.id, [covered, short]);

    const gate = page.getByRole("dialog", { name: GATE });
    await expect(gate).toBeVisible({ timeout: 15000 });
    await expect(gate).toContainText(short.number);
    await expect(gate).not.toContainText(covered.number);
    await expect(gate.getByRole("button", { name: START_ANYWAY })).toBeVisible();
    await gate.getByRole("button", { name: LEAVE_OUT }).click();

    const sheet = page.getByRole("dialog", { name: SHEET });
    await expect(sheet).toBeVisible({ timeout: 15000 });
    await expect(sheet).toContainText(covered.product);
    await expect(sheet).not.toContainText(short.product);
    expect(await openSessionOver(covered.documentId)).toEqual([
      covered.documentId,
    ]);
    expect(await sessionsOf(short.documentId)).toHaveLength(0);
  });

  test("picking a paused session again resumes it whole, without the question", async ({
    page,
    authenticatedPage,
  }, testInfo) => {
    void authenticatedPage;
    const tag = uid(testInfo.workerIndex);
    const partner = await api.createPartner(token, {
      name: `E2E-Cover-Customer-${tag}`,
      type: "CUSTOMER",
    });
    const covered = await newDispatch(partner.id, `Full-${tag}`, 2, false);
    const short = await newDispatch(partner.id, `Short-${tag}`, 4, true);
    const both = [covered.documentId, short.documentId].sort();

    await pickTogether(page, partner.id, [covered, short]);
    const gate = page.getByRole("dialog", { name: GATE });
    await gate.getByRole("button", { name: START_ANYWAY }).click();
    const sheet = page.getByRole("dialog", { name: SHEET });
    await expect(sheet).toBeVisible({ timeout: 15000 });
    // Closing the sheet keeps the session, paused, for the next Pick.
    await sheet.getByRole("button", { name: "Close", exact: true }).click();
    await expect(sheet).toBeHidden();
    await expect
      .poll(async () => (await sessionsOf(covered.documentId))[0]?.status)
      .toBe("paused");

    await pickTogether(page, partner.id, [covered, short]);

    // The session comes back over both documents, as it was started: a
    // choice to leave one out could not be kept, so none is offered.
    await expect(sheet).toBeVisible({ timeout: 15000 });
    await expect(sheet).toContainText(covered.product);
    await expect(sheet).toContainText(short.product);
    await expect(gate).toHaveCount(0);
    expect(await openSessionOver(covered.documentId)).toEqual(both);
  });
});
