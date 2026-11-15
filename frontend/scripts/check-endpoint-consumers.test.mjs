/**
 * The segment rules are the whole gate: loosen them and every route looks
 * consumed, tighten them and every parameterised call looks orphaned. These
 * cases pin the shapes an earlier version of the gate got wrong.
 */
import { readFileSync } from "node:fs";
import { join } from "node:path";

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
        reason: "No screen reads it yet.",
        owner: "maintainers",
        verdict: "to-wire",
        expires: "2026-12-31",
        ...over,
      },
    },
  });
  const byDesign = () => {
    const raw = entry({
      verdict: "integration-only",
      reason: "The print agent polls it.",
    });
    delete raw.routes["/api/v1/x"].expires;
    return raw;
  };

  it("accepts a dated entry that waits for a fix", () => {
    const { claimed, errors, warnings } = readRegister(entry(), today);
    expect([...claimed]).toEqual(["/api/v1/x"]);
    expect(errors).toEqual([]);
    expect(warnings).toEqual([]);
  });

  it("accepts an integration-only entry with no date: it is right by design", () => {
    const { claimed, errors } = readRegister(byDesign(), today);
    expect([...claimed]).toEqual(["/api/v1/x"]);
    expect(errors).toEqual([]);
  });

  it("refuses an entry with no owner or no reason, and stops claiming it", () => {
    for (const over of [{ owner: undefined }, { reason: undefined }]) {
      const { claimed, errors } = readRegister(entry(over), today);
      expect(errors).toHaveLength(1);
      expect(claimed.size).toBe(0);
    }
  });

  it("refuses a date on an entry by design, and none on one that waits", () => {
    const dated = readRegister(
      entry({ verdict: "integration-only" }),
      today,
    ).errors;
    expect(dated).toHaveLength(1);
    expect(dated[0]).toContain("carries no date");
    for (const verdict of ["to-wire", "to-delete", "to-decide"]) {
      const undated = readRegister(
        entry({ verdict, expires: undefined }),
        today,
      ).errors;
      expect(undated).toHaveLength(1);
      expect(undated[0]).toContain("YYYY-MM-DD");
    }
  });

  it("refuses an entry with no verdict or one it does not know", () => {
    for (const verdict of [undefined, "later"]) {
      const { errors } = readRegister(entry({ verdict }), today);
      expect(errors).toHaveLength(1);
      expect(errors[0]).toContain("verdict");
    }
  });

  it("warns on an entry past its date, names its owner, and keeps claiming the route", () => {
    const { claimed, errors, warnings } = readRegister(
      entry({ expires: "2026-01-01" }),
      today,
    );
    expect(errors).toEqual([]);
    expect([...claimed]).toEqual(["/api/v1/x"]);
    expect(warnings).toHaveLength(1);
    expect(warnings[0]).toContain("expired on 2026-01-01");
    expect(warnings[0]).toContain("maintainers");
  });
});

describe("integration-only.json as committed", () => {
  const raw = JSON.parse(
    readFileSync(join(import.meta.dirname, "integration-only.json"), "utf8"),
  );
  const dates = Object.values(raw.routes)
    .map((entry) => entry.expires)
    .filter(Boolean)
    .sort();
  const dayAfterTheLast = new Date(dates.at(-1));
  dayAfterTheLast.setUTCDate(dayAfterTheLast.getUTCDate() + 1);

  // A passed date may only warn, so the register stays whole the day after
  // its last date and on any day after that.
  it.each([dayAfterTheLast, new Date("2099-12-31")])(
    "claims every route it lists and refuses nothing on %s",
    (day) => {
      const { claimed, errors, warnings } = readRegister(raw, day);
      expect(errors).toEqual([]);
      expect(claimed.size).toBe(Object.keys(raw.routes).length);
      expect(warnings).toHaveLength(dates.length);
    },
  );
});
