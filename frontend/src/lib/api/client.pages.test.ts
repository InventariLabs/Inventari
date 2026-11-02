/**
 * A reader that needs the whole list must not stop at the first page. Before
 * the lists moved to the envelope a settings table or a picker got every row
 * in one array; reading only the first page would cut it at the page size
 * without a word.
 */
import { describe, expect, it } from "vitest";
import { http, HttpResponse } from "msw";
import { server } from "@/test/mocks/server";
import { getEveryPage } from "./client";

const ROWS = Array.from({ length: 450 }, (_, i) => ({ id: `row-${i}` }));

describe("getEveryPage", () => {
  it("follows the pages until the server says there are no more", async () => {
    const asked: string[] = [];
    server.use(
      http.get("*/api/v1/rows", ({ request }) => {
        const url = new URL(request.url);
        asked.push(url.search);
        const limit = Number(url.searchParams.get("limit"));
        const offset = Number(url.searchParams.get("offset"));
        return HttpResponse.json({
          items: ROWS.slice(offset, offset + limit),
          total: ROWS.length,
          limit,
          offset,
          has_more: offset + limit < ROWS.length,
        });
      }),
    );

    const rows = await getEveryPage<{ id: string }>("/rows", { usage: "all" });

    expect(rows).toEqual(ROWS);
    expect(asked).toEqual([
      "?usage=all&limit=200&offset=0",
      "?usage=all&limit=200&offset=200",
      "?usage=all&limit=200&offset=400",
    ]);
  });

  it("stops on an empty page even when it is told there is more", async () => {
    let calls = 0;
    server.use(
      http.get("*/api/v1/rows", () => {
        calls += 1;
        return HttpResponse.json({
          items: [],
          total: 5,
          limit: 200,
          offset: 0,
          has_more: true,
        });
      }),
    );

    expect(await getEveryPage("/rows")).toEqual([]);
    expect(calls).toBe(1);
  });
});
