/**
 * Storage-location calls that print, number and found locations.
 *
 * These three sit at the edge of the shelf: a label request that drops the
 * description flag prints the wrong sticker, a generate-code call that goes
 * to the wrong route leaves a location unlabelled, and a hierarchy that
 * loses its steps founds one location instead of a chain.
 */
import { describe, expect, it } from "vitest";
import { http, HttpResponse, type JsonBodyType } from "msw";
import { server } from "@/test/mocks/server";
import { storagesApi } from "./storages";

interface Seen {
  method: string;
  path: string;
  query: Record<string, string>;
  body: unknown;
}

function stub(
  verb: "get" | "post",
  path: string,
  reply: () => Response | JsonBodyType = () => ({}),
): Seen[] {
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
      const answer = reply();
      return answer instanceof Response ? answer : HttpResponse.json(answer);
    }),
  );
  return seen;
}

describe("storagesApi", () => {
  it("prints a label as a file and passes the description flag only when it was decided", async () => {
    const seen = stub("get", "/locations/:id/print", () => {
      return new HttpResponse("png-bytes", {
        headers: { "Content-Type": "image/png" },
      });
    });

    const blob = await storagesApi.printLabel("loc1", "https://app.example");
    await storagesApi.printLabel("loc1", undefined, false);

    expect(blob).toBeInstanceOf(Blob);
    expect(seen[0].path).toBe("/api/v1/locations/loc1/print");
    expect(seen[0].query).toEqual({ base_url: "https://app.example" });
    expect(seen[1].query).toEqual({ show_description: "false" });
  });

  it("asks for a code on the location's own generate route and returns the updated location", async () => {
    const seen = stub("post", "/locations/:id/generate-code", () => ({
      id: "loc1",
      short_code: "AB12",
    }));

    expect(await storagesApi.generateCode("loc1")).toEqual({
      id: "loc1",
      short_code: "AB12",
    });
    expect(seen[0]).toMatchObject({
      method: "POST",
      path: "/api/v1/locations/loc1/generate-code",
    });
  });

  it("posts the chain of steps to the hierarchy route, so a shelf in a new room is founded in one call", async () => {
    const seen = stub("post", "/locations/hierarchy", () => ({ id: "leaf" }));
    const chain = {
      parent_id: "root",
      steps: [{ name: "Room" }, { name: "Shelf" }],
      short_code: "R1",
    };

    expect(await storagesApi.createHierarchy(chain)).toEqual({ id: "leaf" });
    expect(seen[0].body).toEqual(chain);
  });
});
