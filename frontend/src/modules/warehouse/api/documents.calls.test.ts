import { describe, expect, it } from "vitest";
import { http, HttpResponse, type JsonBodyType } from "msw";
import { server } from "@/test/mocks/server";
import { onePage } from "@/test/mocks/page";
import {
  documentApprovalApi,
  documentProfileApi,
  documentsApi,
  inventoryPeriodsApi,
} from "./documents";

interface Seen {
  method: string;
  path: string;
  search: URLSearchParams;
  headers: Headers;
  body: unknown;
}

/**
 * Answer every request under the API with `reply` and record what was sent.
 * The calls below are thin, so what they can get wrong is exactly this: the
 * method, the path, the query string and the body that reach the server.
 */
function record(reply: JsonBodyType = { id: "doc-1" }): Seen[] {
  const seen: Seen[] = [];
  server.use(
    http.all("*/api/v1/*", async ({ request }) => {
      const url = new URL(request.url);
      const text = request.method === "GET" ? "" : await request.text();
      let body: unknown = text || null;
      try {
        body = text ? JSON.parse(text) : null;
      } catch {
        // multipart or blank: keep the raw text
      }
      seen.push({
        method: request.method,
        path: url.pathname.replace(/^.*\/api\/v1/, ""),
        search: url.searchParams,
        headers: request.headers,
        body,
      });
      return HttpResponse.json(reply);
    }),
  );
  return seen;
}

describe("documentsApi — each call reaches the route the server serves", () => {
  it("sends a sheet to the import analyzer and the opening-stock import as multipart", async () => {
    const seen = record({ headers: [] });
    const file = new File(["sku;qty"], "stock.csv", { type: "text/csv" });

    await documentsApi.analyzeImportSheet(file);
    await documentsApi.importOpeningStock(file, { sku: 0 }, "loc-1");

    expect(seen.map((s) => [s.method, s.path])).toEqual([
      ["POST", "/warehouse/import/analyze"],
      ["POST", "/warehouse/import/opening-stock"],
    ]);
    expect(String(seen[1].body)).toContain('{"sku":0}');
    expect(String(seen[1].body)).toContain("loc-1");
  });

  it("asks the floor queue with its filters and reads the week's measures", async () => {
    const seen = record({ items: [] });

    await documentsApi.todo({ date_to: "2026-10-27", view: "mine" });
    await documentsApi.workMeasures();

    expect(seen[0].path).toBe("/warehouse/todo");
    expect(seen[0].search.get("date_to")).toBe("2026-10-27");
    expect(seen[0].search.get("view")).toBe("mine");
    expect(seen[1].path).toBe("/warehouse/work-items/measures");
  });

  it("starts a scheduled count and manages custom tasks", async () => {
    const seen = record({ id: "st-1" });

    await expect(documentsApi.startCount("sch-1")).resolves.toEqual({
      id: "st-1",
    });
    await documentsApi.createCustomWorkItem({ title: "Sweep aisle 3" });
    await documentsApi.setCustomWorkItemDone("ci-1", true);
    await documentsApi.deleteCustomWorkItem("ci-1");

    expect(seen.map((s) => [s.method, s.path, s.body])).toEqual([
      ["POST", "/stock-takes/cycle-count-schedules/sch-1/run", null],
      ["POST", "/warehouse/work-items/custom", { title: "Sweep aisle 3" }],
      ["PUT", "/warehouse/work-items/custom/ci-1/done", { done: true }],
      ["DELETE", "/warehouse/work-items/custom/ci-1", null],
    ]);
  });

  it("puts away a receipt line, sending no scan as null rather than leaving it out", async () => {
    const seen = record({ move_id: "m-1" });

    await documentsApi.putAwayWorkItem({ lineId: "l-1", locationId: "loc-9" });
    await documentsApi.putAwayWorkItem({
      lineId: "l-2",
      locationId: "loc-9",
      scannedCode: "A-01",
    });

    expect(seen[0].path).toBe("/warehouse/work-items/putaway/l-1");
    expect(seen[0].body).toEqual({ location_id: "loc-9", scanned_code: null });
    expect(seen[1].body).toEqual({
      location_id: "loc-9",
      scanned_code: "A-01",
    });
  });

  it("reads and posts a replenishment proposal, with the scan only when one was made", async () => {
    const seen = record({ lines: [] });

    await documentsApi.getReplenishmentProposal("rule-1");
    await documentsApi.postReplenishmentProposal({ ruleId: "rule-1" });
    await documentsApi.postReplenishmentProposal({
      ruleId: "rule-1",
      scannedCode: "R-02",
    });

    expect(seen[0].path).toBe(
      "/purchase-orders/replenishment/proposals/rule-1",
    );
    expect(seen[1].path).toBe(
      "/purchase-orders/replenishment/proposals/rule-1/move",
    );
    expect(seen[1].search.has("scanned_code")).toBe(false);
    expect(seen[2].search.get("scanned_code")).toBe("R-02");
  });

  it("lists what awaits the reader's approval and asks a price hint without an empty partner", async () => {
    const seen = record({ items: [], total: 0 });

    await documentsApi.listAwaitingMyApproval({ limit: 5 });
    await documentsApi.priceHint({ template_id: "pt-1", partner_id: null });
    await documentsApi.priceHint({ template_id: "pt-1", partner_id: "p-1" });

    expect(seen[0].path).toBe("/warehouse/awaiting-my-approval");
    expect(seen[0].search.get("limit")).toBe("5");
    expect(seen[1].search.get("template_id")).toBe("pt-1");
    expect(seen[1].search.has("partner_id")).toBe(false);
    expect(seen[2].search.get("partner_id")).toBe("p-1");
  });

  it("posts a new document under the press's idempotency key, and the surplus yes only when given", async () => {
    const seen = record();

    await documentsApi.postNew({ type: "IN" } as never, "key-1");
    await documentsApi.postNew({ type: "IN" } as never, "key-2", true);

    expect(seen[0].path).toBe("/warehouse/documents/post");
    expect(seen[0].headers.get("Idempotency-Key")).toBe("key-1");
    expect(seen[0].search.has("confirm_surplus")).toBe(false);
    expect(seen[1].headers.get("Idempotency-Key")).toBe("key-2");
    expect(seen[1].search.get("confirm_surplus")).toBe("true");
  });

  it("sets a line's target and a module's fields on the document or on one line", async () => {
    const seen = record();

    await documentsApi.setLineTarget("doc-1", "l-1", null);
    await documentsApi.setMetaData({
      docId: "doc-1",
      module: "acme/lots",
      values: { batch: "B1" },
    });
    await documentsApi.setMetaData({
      docId: "doc-1",
      lineId: "l-1",
      module: "lots",
      values: null,
    });

    expect(seen.map((s) => [s.method, s.path, s.body])).toEqual([
      [
        "PATCH",
        "/warehouse/documents/doc-1/lines/l-1",
        { target_location_id: null },
      ],
      [
        "PUT",
        "/warehouse/documents/doc-1/meta-data/acme%2Flots",
        { batch: "B1" },
      ],
      ["PUT", "/warehouse/documents/doc-1/lines/l-1/meta-data/lots", {}],
    ]);
  });

  it("creates, updates and confirms a document on its own routes", async () => {
    const seen = record();

    await documentsApi.create({ type: "IN" } as never);
    await documentsApi.update("doc-1", { notes: "dock 2" } as never);
    await documentsApi.confirm("doc-1");

    expect(seen.map((s) => [s.method, s.path, s.body])).toEqual([
      ["POST", "/warehouse/documents", { type: "IN" }],
      ["PUT", "/warehouse/documents/doc-1", { notes: "dock 2" }],
      ["PATCH", "/warehouse/documents/doc-1/confirm", null],
    ]);
  });

  it("drives a document through post, duplicate, undo and delete", async () => {
    const seen = record();

    await documentsApi.postNow("doc-1");
    await documentsApi.duplicate("doc-1");
    await documentsApi.undo("doc-1");
    await documentsApi.delete("doc-1");

    expect(seen.map((s) => [s.method, s.path])).toEqual([
      ["POST", "/warehouse/documents/doc-1/post"],
      ["POST", "/warehouse/documents/doc-1/duplicate"],
      ["POST", "/warehouse/documents/doc-1/undo"],
      ["DELETE", "/warehouse/documents/doc-1"],
    ]);
  });

  it("downloads one PDF and a batch, keeping the chosen order and the language", async () => {
    const seen = record();

    await documentsApi.downloadPdf("doc-1", "pl");
    await documentsApi.downloadPdfBatch(["doc-2", "doc-1"], "de");

    expect(seen[0].path).toBe("/warehouse/documents/doc-1/pdf");
    expect(seen[0].search.get("lang")).toBe("pl");
    expect(seen[1].path).toBe("/warehouse/documents/pdf");
    expect(seen[1].search.getAll("ids")).toEqual(["doc-2", "doc-1"]);
    expect(seen[1].search.get("lang")).toBe("de");
  });

  it("creates corrections and returns, and reads every page of a document's corrections", async () => {
    const seen = record();
    server.use(
      http.get("*/warehouse/documents/:id/corrections", () =>
        HttpResponse.json(onePage([{ id: "kor-1" }])),
      ),
    );

    await documentsApi.createCorrection({ document_id: "doc-1" } as never);
    await documentsApi.createReturn("doc-1", { lines: [] } as never);
    await expect(documentsApi.listCorrections("doc-1")).resolves.toEqual([
      { id: "kor-1" },
    ]);

    expect(seen.map((s) => [s.method, s.path])).toEqual([
      ["POST", "/warehouse/corrections"],
      ["POST", "/warehouse/documents/doc-1/return"],
    ]);
  });

  it("reads the register's summary and rows, and asks its export as CSV", async () => {
    const seen = record({ rows: [] });
    const params = { date_from: "2026-10-01", date_to: "2026-10-31" };

    await documentsApi.getRegisterSummary(params as never);
    await documentsApi.getRegisterRows(params as never);
    await documentsApi.getRegisterCsv(params as never);

    expect(seen.map((s) => s.path)).toEqual([
      "/warehouse/register/summary",
      "/warehouse/register/rows",
      "/warehouse/register",
    ]);
    expect(seen[2].search.get("output_format")).toBe("csv");
    expect(seen[2].headers.get("Accept")).toBe("text/csv");
    expect(seen[2].search.get("date_from")).toBe("2026-10-01");
  });
});

describe("documentProfileApi — presets travel with their names escaped", () => {
  it("applies a preset and reads one preset's values by an encoded name", async () => {
    const seen = record({ name: "x" });

    await documentProfileApi.applyPreset("food & home");
    await documentProfileApi.getPresetValues("food & home");

    expect(seen.map((s) => [s.method, s.path])).toEqual([
      ["POST", "/warehouse/profile/apply-preset/food%20%26%20home"],
      ["GET", "/warehouse/profile/presets/food%20%26%20home"],
    ]);
  });
});

describe("documentApprovalApi — decisions go through the document's own routes", () => {
  it("approves and rejects with notes only when written", async () => {
    const seen = record({ id: "ap-1" });

    await documentApprovalApi.approve("doc-1");
    await documentApprovalApi.reject("doc-1", "wrong supplier");

    expect(seen[0].path).toBe("/approvals/documents/doc-1/approve");
    expect(seen[0].search.has("notes")).toBe(false);
    expect(seen[1].path).toBe("/approvals/documents/doc-1/reject");
    // A query string is what proxies and access logs keep.
    expect(seen[1].search.has("notes")).toBe(false);
    expect(seen[1].body).toEqual({ notes: "wrong supplier" });
  });

  it("reads the approval requirement of a document", async () => {
    const seen = record({ required: true });

    await expect(documentApprovalApi.getRequirement("doc-1")).resolves.toEqual({
      required: true,
    });
    expect(seen[0].path).toBe(
      "/approvals/documents/doc-1/approval-requirement",
    );
  });
});

describe("inventoryPeriodsApi — closing and reopening a month", () => {
  it("lists a year's periods and closes and reopens a month with optional notes", async () => {
    const seen = record({ year: 2026, month: 9 });
    server.use(
      http.get("*/warehouse/periods", ({ request }) => {
        seen.push({
          method: "GET",
          path: "/warehouse/periods",
          search: new URL(request.url).searchParams,
          headers: request.headers,
          body: null,
        });
        return HttpResponse.json(onePage([{ year: 2026, month: 9 }]));
      }),
    );

    await expect(inventoryPeriodsApi.list(2026)).resolves.toHaveLength(1);
    await inventoryPeriodsApi.close(2026, 9, "audited");
    await inventoryPeriodsApi.reopen(2026, 9);

    expect(seen[0].search.get("year")).toBe("2026");
    expect(seen.slice(1).map((s) => [s.method, s.path, s.body])).toEqual([
      ["POST", "/warehouse/periods/2026/9/close", { notes: "audited" }],
      ["POST", "/warehouse/periods/2026/9/reopen", null],
    ]);
  });
});
