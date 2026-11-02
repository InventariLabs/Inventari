import { describe, it, expect } from "vitest";
import { http, HttpResponse } from "msw";

import { server } from "@/test/mocks/server";
import { moduleRegistry } from "@/lib/moduleRegistry";
import "./module";

/**
 * Someone holding a device types the number off its sticker into the
 * global search. The failure caught: the module's search answering with the
 * product screen's path (where assets are not shown), or not passing the
 * typed text to the asset list at all.
 */
describe("equipment module — global search", () => {
  it("asks the asset list for the typed text and leads to the asset itself", async () => {
    let asked: URLSearchParams | null = null;
    server.use(
      http.get("/api/v1/equipment/assets", ({ request }) => {
        asked = new URL(request.url).searchParams;
        return HttpResponse.json({
          items: [
            { id: "a-1", name: "ThinkPad T14", serial_number: "PF-3XK9" },
            { id: "a-2", name: "Dock", serial_number: null },
          ],
          total: 2,
          offset: 0,
          limit: 5,
          has_more: false,
        });
      }),
    );

    const search = moduleRegistry.getModule("equipment")!.searchProvider!;
    const results = await search("PF-3XK9");

    const params = asked as unknown as URLSearchParams;
    expect(params.get("search")).toBe("PF-3XK9");
    expect(params.get("limit")).toBe("5");
    expect(results).toEqual([
      {
        id: "equipment-a-1",
        title: "ThinkPad T14",
        subtitle: "PF-3XK9",
        path: "/equipment/a-1",
        module: "equipment",
      },
      {
        id: "equipment-a-2",
        title: "Dock",
        subtitle: undefined,
        path: "/equipment/a-2",
        module: "equipment",
      },
    ]);
  });
});
