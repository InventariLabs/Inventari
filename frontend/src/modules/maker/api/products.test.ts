/**
 * The maker's product search feeds every quick-create panel of the module
 * (formula, ingredient, cook for stock, production run). The endpoint refuses
 * search text above 100 characters while a product name may be 255, so a long
 * name must go out cut, or the panel never gets to offer "add as new".
 */
import { describe, expect, it } from "vitest";
import { http, HttpResponse } from "msw";
import { server } from "@/test/mocks/server";
import { makerProductsApi } from "./products";

function stubSearch(): string[] {
  const seen: string[] = [];
  server.use(
    http.get("*/api/v1/items/product-templates", ({ request }) => {
      seen.push(new URL(request.url).searchParams.get("search") ?? "");
      return HttpResponse.json([]);
    }),
  );
  return seen;
}

describe("makerProductsApi.search", () => {
  it("sends no more of a long name than the endpoint accepts", async () => {
    const seen = stubSearch();

    await makerProductsApi.search("A".repeat(150) + "B".repeat(105));

    expect(seen).toEqual(["A".repeat(100)]);
  });

  it("still sends a request when the cut would fall inside an emoji", async () => {
    const seen = stubSearch();

    await makerProductsApi.search("x".repeat(99) + "😀" + "more text");

    expect(seen).toEqual(["x".repeat(99) + "😀"]);
  });
});
