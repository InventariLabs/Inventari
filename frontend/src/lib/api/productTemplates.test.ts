/**
 * The product-template calls send the fields the quick-create and the
 * threshold screens depend on.
 *
 * A scanned barcode that is dropped on create means the next scan of the
 * same box finds nothing; an empty brand sent as "" instead of left out
 * overwrites what the server would have defaulted. Each is silent.
 */
import { describe, expect, it } from "vitest";
import { http, HttpResponse, type JsonBodyType } from "msw";
import { server } from "@/test/mocks/server";
import { productTemplatesApi } from "./productTemplates";

interface Seen {
  method: string;
  path: string;
  query: Record<string, string>;
  body: unknown;
}

type Verb = "get" | "post" | "patch";

function stub(verb: Verb, path: string, reply: JsonBodyType = {}): Seen[] {
  const seen: Seen[] = [];
  server.use(
    http[verb](`*/api/v1${path}`, async ({ request }) => {
      const url = new URL(request.url);
      const text = await request.text();
      seen.push({
        method: request.method,
        path: url.pathname,
        query: Object.fromEntries(url.searchParams),
        body: text ? JSON.parse(text) : undefined,
      });
      return HttpResponse.json(reply);
    }),
  );
  return seen;
}

describe("productTemplatesApi", () => {
  it("gets one template from its own route", async () => {
    const seen = stub("get", "/items/product-templates/:id", { id: "t1" });

    expect(await productTemplatesApi.get("t1")).toEqual({ id: "t1" });
    expect(seen[0].path).toBe("/api/v1/items/product-templates/t1");
  });

  it("searches with the term and a default limit of ten", async () => {
    const rows = [{ id: "t1" }];
    const seen = stub("get", "/items/product-templates", rows);

    expect(await productTemplatesApi.search("milk")).toEqual(rows);
    expect(seen[0].query).toEqual({ search: "milk", limit: "10" });
  });

  it("creates a product from a name and a unit and carries the scanned codes with it", async () => {
    const seen = stub("post", "/items/product-templates", { id: "t1" });

    await productTemplatesApi.create("Milk", "u1", {
      brand: "Acme",
      barcode: "590123",
    });

    expect(seen[0].body).toEqual({
      name: "Milk",
      uom_id: "u1",
      brand: "Acme",
      barcode: "590123",
    });
  });

  it("leaves empty codes out of the body instead of sending blank strings", async () => {
    const seen = stub("post", "/items/product-templates", { id: "t1" });

    await productTemplatesApi.create("Milk", "u1", { brand: "", barcode: "" });

    expect(seen[0].body).toEqual({ name: "Milk", uom_id: "u1" });
  });

  it("returns only the barcode string a generate call produced", async () => {
    stub("post", "/items/product-templates/generate-barcode", {
      barcode: "2000000000015",
    });

    expect(await productTemplatesApi.generateBarcode()).toBe("2000000000015");
  });

  it("returns the count as a number, not the envelope", async () => {
    stub("get", "/items/product-templates/count", { count: 42 });

    expect(await productTemplatesApi.count()).toBe(42);
  });

  it("reads the organization's total stock of one product from its stock route", async () => {
    const stock = {
      product_template_id: "t1",
      total_quantity: "3.5",
      uom_symbol: "kg",
    };
    const seen = stub("get", "/items/product-templates/:id/stock", stock);

    expect(await productTemplatesApi.getStock("t1")).toEqual(stock);
    expect(seen[0].path).toBe("/api/v1/items/product-templates/t1/stock");
  });

  it("patches the nutrition and sends null to clear it, so clearing is not a no-op", async () => {
    const seen = stub("patch", "/items/product-templates/:id/nutrition");

    await productTemplatesApi.updateNutrition("t1", { calories_kcal: 52 });
    await productTemplatesApi.updateNutrition("t1", null);

    expect(seen[0].body).toEqual({ nutrition_info: { calories_kcal: 52 } });
    expect(seen[1].body).toEqual({ nutrition_info: null });
    expect(seen[0].path).toBe("/api/v1/items/product-templates/t1/nutrition");
  });
});
