/**
 * The POSTs that compute or probe and save nothing, run through their real
 * wrappers on a session that has ended: each is told so in the sentence that
 * does not claim the user's work was lost.
 */
import { describe, expect, it } from "vitest";
import { http, HttpResponse } from "msw";
import i18next from "i18next";
import { server } from "@/test/mocks/server";
import { extractApiError } from "@/lib/errors";
import { tokenStore } from "./client";
import { aiConnectionsApi } from "./aiConnections";
import { organizationsApi } from "./organizations";
import { productTemplatesApi } from "./productTemplates";
import { pricingApi } from "@/modules/maker/api/pricing";
import { recipesLinkingApi } from "@/modules/recipes/api/recipes_linking";
import { documentsPickingApi } from "@/modules/warehouse/api/documents_picking";
import { webhooksApi } from "@/modules/webhooks/api/webhooks";

const calls: [string, string, () => Promise<unknown>][] = [
  [
    "/maker/pricing/compute",
    "pricing",
    () =>
      pricingApi.compute({
        template_id: "t-1",
        produced_qty: 1,
        target_margin_pct: 10,
      } as never),
  ],
  [
    "/recipes/ingredients/match-proposals",
    "match proposals",
    () => recipesLinkingApi.suggestIngredientMatches(),
  ],
  [
    "/warehouse/picking/coverage",
    "picking coverage",
    () => documentsPickingApi.wmsPickingCoverage(["d-1"]),
  ],
  [
    "/ai-connections/test",
    "AI connection test",
    () => aiConnectionsApi.test({ provider: "openai" } as never),
  ],
  [
    "/webhooks/endpoints/w-1/test",
    "webhook test",
    () => webhooksApi.test("w-1"),
  ],
  [
    "/organizations/my/test-email",
    "test e-mail",
    () => organizationsApi.testEmail({}),
  ],
  [
    "/items/product-templates/generate-barcode",
    "barcode generation",
    () => productTemplatesApi.generateBarcode(),
  ],
];

describe("a POST that saves nothing, on an ended session", () => {
  it.each(calls)(
    "%s (%s) is not told it saved nothing",
    async (url, _n, run) => {
      server.use(
        http.post(`*/api/v1${url}`, () =>
          HttpResponse.json({ detail: "stale token" }, { status: 401 }),
        ),
        http.post(
          "*/api/v1/auth/refresh",
          () => new HttpResponse(null, { status: 204 }),
        ),
      );
      tokenStore.set("expired-token");

      const message = await run().then(
        () => null,
        (e: unknown) => extractApiError(e, "Failed"),
      );
      expect(message).toBe(i18next.t("common:errors.sessionEndedRead"));
    },
  );
});
