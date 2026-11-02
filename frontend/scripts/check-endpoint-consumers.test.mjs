/**
 * The segment rules are the whole gate: loosen them and every route looks
 * consumed, tighten them and every parameterised call looks orphaned. These
 * cases pin the shapes an earlier version of the gate got wrong.
 */
import { describe, expect, it } from "vitest";

import {
  callMatches,
  callsIn,
  readRegister,
  routesIn,
  unclaimedRoutes,
} from "./check-endpoint-consumers.mjs";

describe("callsIn", () => {
  it("reads both HTTP clients and a template literal", () => {
    expect(callsIn('api.get("/organizations/my")')).toEqual([
      "/organizations/my",
    ]);
    expect(callsIn("http.delete(`/items/${id}`)")).toEqual(["/items/${id}"]);
  });

  it("reads through a type argument, including one spanning lines", () => {
    expect(callsIn('api.get<Item[]>("/items")')).toEqual(["/items"]);
    expect(
      callsIn(
        'api.get<\n  import("@/x").Thing | null\n>(`/warehouse/documents/${id}/approval`)',
      ),
    ).toEqual(["/warehouse/documents/${id}/approval"]);
  });

  it("strips the query string and a trailing slash", () => {
    expect(callsIn('api.get("/items?expiring_days=7")')).toEqual(["/items"]);
  });

  it("reads the paged-list reader as a call, and not its own definition", () => {
    expect(callsIn('getEveryPage<Uom>("/uoms")')).toEqual(["/uoms"]);
    expect(
      callsIn("export async function getEveryPage<T>(url: string) {}"),
    ).toEqual([]);
  });

  it("ignores a call whose path is built elsewhere", () => {
    expect(callsIn("api.get(url)")).toEqual([]);
  });
});

describe("callMatches", () => {
  it("matches a literal path and a hole against a param", () => {
    expect(callMatches("/items", "/items")).toBe(true);
    expect(callMatches("/items/${id}", "/items/{item_id}")).toBe(true);
  });

  it("refuses a trailing hole standing in for a literal segment", () => {
    // The rule that matters most: without it this call consumes the
    // whole cycle-count feature and reports it as built.
    expect(
      callMatches("/stock-takes/${id}", "/stock-takes/cycle-count-schedules"),
    ).toBe(false);
  });

  it("allows a hole over a literal when a literal segment still follows", () => {
    // The shared template client addresses every module this way.
    expect(
      callMatches(
        "/${module}/templates/placeholders",
        "/warehouse/templates/placeholders",
      ),
    ).toBe(true);
  });

  it("refuses paths of different depth", () => {
    expect(callMatches("/items", "/items/{item_id}")).toBe(false);
    expect(callMatches("/items/${id}/lots", "/items/{item_id}")).toBe(false);
  });
});

describe("unclaimedRoutes", () => {
  it("reports only versioned API routes nothing calls", () => {
    const routes = [
      "/",
      "/health",
      "/api/v1/items",
      "/api/v1/stats/reconciliation",
    ];
    expect(unclaimedRoutes(routes, ["/items"])).toEqual([
      "/api/v1/stats/reconciliation",
    ]);
  });
});

describe("routesIn", () => {
  it("reads the generated table", () => {
    expect(
      routesIn('export const API_ROUTES = [\n  "/api/v1/items",\n];'),
    ).toEqual(["/api/v1/items"]);
  });
});

describe("readRegister", () => {
  const today = new Date("2026-08-23");
  const entry = (over) => ({
    routes: {
      "/api/v1/x": {
        reason: "Print agent polls it.",
        owner: "maintainers",
        expires: "2026-12-31",
        ...over,
      },
    },
  });

  it("accepts a complete entry", () => {
    const { claimed, errors } = readRegister(entry(), today);
    expect([...claimed]).toEqual(["/api/v1/x"]);
    expect(errors).toEqual([]);
  });

  it("refuses an entry with no owner, no reason or no expiry", () => {
    expect(
      readRegister(entry({ owner: undefined }), today).errors,
    ).toHaveLength(1);
    expect(
      readRegister(entry({ reason: undefined }), today).errors,
    ).toHaveLength(1);
    expect(
      readRegister(entry({ expires: undefined }), today).errors,
    ).toHaveLength(1);
  });

  it("refuses an entry past its date, and stops claiming the route", () => {
    const { claimed, errors } = readRegister(
      entry({ expires: "2026-01-01" }),
      today,
    );
    expect(claimed.size).toBe(0);
    expect(errors[0]).toContain("expired");
  });
});
