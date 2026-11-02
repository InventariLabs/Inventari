import { describe, expect, it } from "vitest";
import { http, HttpResponse } from "msw";
import { server } from "@/test/mocks/server";
import { documentsReceivingApi } from "./documents_receiving";

function recordBodies() {
  const bodies: Record<string, unknown>[] = [];
  server.use(
    http.post(
      "*/api/v1/warehouse/documents/*/receiving/*/short-receive",
      async ({ request }) => {
        bodies.push((await request.json()) as Record<string, unknown>);
        return HttpResponse.json({ status: "short_receive_confirmed" });
      },
    ),
  );
  return bodies;
}

/**
 * The server accepts a discrepancy code from its enum or none at all; an
 * empty string is a 422 and nothing is received. A full count carries no
 * code, so whichever caller means "none" must not put a blank on the wire.
 */
describe("documentsReceivingApi.wmsReceivingShortReceive", () => {
  it("sends no discrepancy code when the caller has none to name", async () => {
    const bodies = recordBodies();
    await documentsReceivingApi.wmsReceivingShortReceive("d", "s", "l", 5, "");
    expect(bodies).toHaveLength(1);
    expect(bodies[0]).not.toHaveProperty("discrepancy_code", "");
    expect(bodies[0].discrepancy_code ?? null).toBeNull();
  });

  it("still sends the code the worker chose for a short or held receipt", async () => {
    const bodies = recordBodies();
    await documentsReceivingApi.wmsReceivingShortReceive(
      "d",
      "s",
      "l",
      3,
      "damaged",
    );
    expect(bodies[0].discrepancy_code).toBe("damaged");
  });
});
