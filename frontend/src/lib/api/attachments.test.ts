/**
 * An item's attachments go to the item's route and come back as a list.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { http, HttpResponse } from "msw";
import { server } from "@/test/mocks/server";
import { onePage } from "@/test/mocks/page";
import { api } from "./client";
import { attachmentsApi } from "./attachments";

vi.mock("@/lib/imageUtils", () => ({
  prepareImageUpload: vi.fn(async (f: File) => f),
}));

afterEach(() => {
  vi.restoreAllMocks();
});

describe("attachmentsApi", () => {
  it("posts the file as the file field on the item's attachments route", async () => {
    const saved = { id: "a1" };
    const post = vi.spyOn(api, "post").mockResolvedValue({ data: saved });
    const file = new File(["pdf"], "manual.pdf", { type: "application/pdf" });

    expect(await attachmentsApi.upload("i1", file)).toEqual(saved);

    expect(post.mock.calls[0][0]).toBe("/items/i1/attachments");
    expect((post.mock.calls[0][1] as FormData).get("file")).toBe(file);
  });

  it("refuses a file above the limit before sending it, so the bytes are not paid for first", async () => {
    const post = vi.spyOn(api, "post");
    const big = new File([new Uint8Array(11 * 1024 * 1024)], "big.pdf", {
      type: "application/pdf",
    });

    await expect(attachmentsApi.upload("i1", big)).rejects.toThrow(
      "File too large",
    );
    expect(post).not.toHaveBeenCalled();
  });

  it("lists an item's attachments as one array", async () => {
    const rows = [{ id: "a1" }];
    let path = "";
    server.use(
      http.get("*/api/v1/items/:id/attachments", ({ request }) => {
        path = new URL(request.url).pathname;
        return HttpResponse.json(onePage(rows));
      }),
    );

    expect(await attachmentsApi.list("i1")).toEqual(rows);
    expect(path).toBe("/api/v1/items/i1/attachments");
  });

  it("deletes an attachment by its own id, not through the item", async () => {
    let seen = "";
    server.use(
      http.delete("*/api/v1/attachments/:id", ({ request }) => {
        seen = new URL(request.url).pathname;
        return new HttpResponse(null, { status: 204 });
      }),
    );

    await attachmentsApi.delete("a1");

    expect(seen).toBe("/api/v1/attachments/a1");
  });
});
