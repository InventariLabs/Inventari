import {
  expect,
  type APIRequestContext,
  type Page,
  type PlaywrightWorkerArgs,
  type TestInfo,
} from "@playwright/test";
import { ADMIN_EMAIL, ADMIN_PASSWORD } from "../fixtures/credentials";
import { ApiHelper } from "./api";

/**
 * What the receiving walks start from: a supplier, a shelf, products with
 * barcodes and an order waiting for them, all named for this one test so no
 * two workers meet on the same row.
 *
 * Everything is read back through the API, because the promise of receiving
 * is in the ledger and on the order, not in a banner.
 */

let sequence = 0;

/** A valid EAN-13, drawn at random: two tests of one run do not share one. */
function uniqueEan13(): string {
  const body = `400639${String(Math.floor(Math.random() * 1_000_000)).padStart(6, "0")}`;
  let sum = 0;
  for (let i = 0; i < 12; i++) sum += Number(body[i]) * (i % 2 === 0 ? 1 : 3);
  return body + String((10 - (sum % 10)) % 10);
}

export interface SeededProduct {
  id: string;
  name: string;
  barcode: string;
}

export interface SeededShelf {
  id: string;
  name: string;
  /** What the printed label says; scanned to confirm the goods lie there. */
  code: string;
}

export interface SeededPartner {
  id: string;
  name: string;
}

export interface SeededOrder {
  id: string;
  number: string;
}

export interface OrderLineState {
  name: string;
  ordered: number;
  received: number;
}

export class ReceivingSeed {
  constructor(
    readonly api: ApiHelper,
    readonly request: APIRequestContext,
    readonly token: string,
    readonly uid: string,
  ) {}

  private auth() {
    return { Authorization: `Bearer ${this.token}` };
  }

  async product(label: string): Promise<SeededProduct> {
    const name = `E2E-Recv-${label}-${this.uid}`;
    // Two draws of one seed never meet; two seeds meet once in a million.
    let barcode = uniqueEan13();
    while (this.barcodes.has(barcode)) {
      barcode = this.nextBarcode(barcode);
    }
    this.barcodes.add(barcode);
    const template = await this.api.createProductTemplate(this.token, {
      name,
      barcode,
    });
    return { id: template.id, name, barcode };
  }

  private barcodes = new Set<string>();

  /** The next valid EAN-13 after `code`, by its twelve-digit body. */
  private nextBarcode(code: string): string {
    const body = String(Number(code.slice(0, 12)) + 1).padStart(12, "0");
    let sum = 0;
    for (let i = 0; i < 12; i++) sum += Number(body[i]) * (i % 2 === 0 ? 1 : 3);
    return body + String((10 - (sum % 10)) % 10);
  }

  async shelf(label: string): Promise<SeededShelf> {
    const name = `E2E-Recv-${label}-${this.uid}`;
    const created = await this.api.createStorageIdempotent(this.token, {
      name,
      location_type: "SHELF",
    });
    const read = await this.request.get(`/api/v1/locations/${created.id}`, {
      headers: this.auth(),
    });
    const body = (await read.json()) as { short_code: string };
    return { id: created.id, name, code: body.short_code };
  }

  async partner(
    label: string,
    type: "SUPPLIER" | "CUSTOMER",
  ): Promise<SeededPartner> {
    const name = `E2E-Recv-${label}-${this.uid}`;
    const partner = await this.api.createPartner(this.token, { name, type });
    return { id: partner.id, name };
  }

  /** A confirmed purchase order: the shape in which a delivery is waiting. */
  async order(
    supplier: SeededPartner,
    lines: Array<{ product: SeededProduct; quantity: number }>,
  ): Promise<SeededOrder> {
    const created = await this.api.createPurchaseOrder(this.token, {
      partner_id: supplier.id,
      lines: lines.map((line) => ({
        product_template_id: line.product.id,
        quantity_ordered: line.quantity,
      })),
    });
    const confirmed = await this.request.post(
      `/api/v1/purchase-orders/${created.id}/confirm`,
      { headers: this.auth() },
    );
    if (!confirmed.ok()) {
      throw new Error(`Could not confirm the order: ${await confirmed.text()}`);
    }
    const order = (await confirmed.json()) as SeededOrder;
    return { id: order.id, number: order.number };
  }

  async orderLines(order: SeededOrder): Promise<OrderLineState[]> {
    const read = await this.request.get(`/api/v1/purchase-orders/${order.id}`, {
      headers: this.auth(),
    });
    const body = (await read.json()) as {
      lines: Array<{
        name: string;
        quantity_ordered: string;
        quantity_received: string;
      }>;
    };
    return body.lines.map((line) => ({
      name: line.name,
      ordered: Number(line.quantity_ordered),
      received: Number(line.quantity_received),
    }));
  }

  async orderStatus(order: SeededOrder): Promise<string> {
    const read = await this.request.get(`/api/v1/purchase-orders/${order.id}`, {
      headers: this.auth(),
    });
    return ((await read.json()) as { status: string }).status;
  }

  onHand(product: SeededProduct, shelf: SeededShelf): Promise<number> {
    return this.api.quantityOnHand(this.token, product.id, shelf.id);
  }

  /** The document a result screen links to, read off its own link. */
  async documentLinkedFrom(page: Page): Promise<Record<string, unknown>> {
    const link = page
      .getByRole("link", { name: /^[A-Z]{2,}\/\d{4}\/\d+$/ })
      .first();
    await expect(link).toBeVisible();
    const href = await link.getAttribute("href");
    const id = href?.split("/").pop();
    if (!id) throw new Error(`The result links to no document: ${href}`);
    return this.api.getDocument(this.token, id);
  }

  /** The partner a document names, with the role it was created in. */
  async partnerOf(
    document: Record<string, unknown>,
  ): Promise<{ id: string; type: string } | null> {
    const id = document.partner_id as string | null;
    if (!id) return null;
    const partner = (await this.api.getPartner(this.token, id)) as {
      id: string;
      type: string;
    };
    return { id: partner.id, type: partner.type };
  }
}

/** One seed per test: a login of its own and a name stamp of its own. */
export async function startSeed(
  { playwright }: Pick<PlaywrightWorkerArgs, "playwright">,
  baseURL: string | undefined,
  testInfo: TestInfo,
): Promise<ReceivingSeed> {
  const request = await playwright.request.newContext({ baseURL });
  const api = new ApiHelper(request);
  const token = (await api.login(ADMIN_EMAIL, ADMIN_PASSWORD)).access_token;
  await api.completeOnboarding(token);
  await api.enableAllModules(token);
  const uid = `${Date.now().toString(36)}-w${testInfo.workerIndex}-${sequence++}`;
  return new ReceivingSeed(api, request, token, uid);
}
