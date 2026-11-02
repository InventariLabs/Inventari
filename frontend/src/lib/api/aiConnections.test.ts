/**
 * The AI connection calls carry exactly what each route accepts.
 *
 * The test endpoint refuses extra fields, so a draft that carries its name
 * or tuning knobs turns "does this key work" into a 422 about the name. The
 * wrapper builds that payload field by field; this pins it.
 */
import { describe, expect, it } from "vitest";
import { http, HttpResponse, type JsonBodyType } from "msw";
import { server } from "@/test/mocks/server";
import { onePage } from "@/test/mocks/page";
import type { AiConnectionDraft } from "@/types/ai";
import { aiConnectionsApi } from "./aiConnections";

interface Seen {
  method: string;
  path: string;
  body: unknown;
}

function stub(
  verb: "get" | "post" | "put" | "delete",
  path: string,
  reply: JsonBodyType = {},
  status = 200,
): Seen[] {
  const seen: Seen[] = [];
  server.use(
    http[verb](`*/api/v1${path}`, async ({ request }) => {
      const text = await request.text();
      seen.push({
        method: request.method,
        path: new URL(request.url).pathname,
        body: text ? JSON.parse(text) : undefined,
      });
      return status === 204
        ? new HttpResponse(null, { status })
        : HttpResponse.json(reply, { status });
    }),
  );
  return seen;
}

describe("aiConnectionsApi", () => {
  it("lists the connections across pages as one array", async () => {
    const rows = [{ id: "c1" }];
    stub("get", "/ai-connections", onePage(rows));

    expect(await aiConnectionsApi.list()).toEqual(rows);
  });

  it("posts a new connection draft whole, so the key and model are saved together", async () => {
    const seen = stub("post", "/ai-connections", { id: "c1" }, 201);
    const draft = { name: "Main", provider: "openai" } as AiConnectionDraft;

    expect(await aiConnectionsApi.create(draft)).toEqual({ id: "c1" });
    expect(seen[0]).toMatchObject({ method: "POST", body: draft });
  });

  it("puts changes on the connection's own route, so another connection is not overwritten", async () => {
    const seen = stub("put", "/ai-connections/:id", { id: "c1" });

    await aiConnectionsApi.update("c1", { name: "Renamed" });

    expect(seen[0]).toMatchObject({
      method: "PUT",
      path: "/api/v1/ai-connections/c1",
      body: { name: "Renamed" },
    });
  });

  it("deletes the named connection", async () => {
    const seen = stub("delete", "/ai-connections/:id", undefined, 204);

    await aiConnectionsApi.delete("c1");

    expect(seen[0]).toMatchObject({
      method: "DELETE",
      path: "/api/v1/ai-connections/c1",
    });
  });

  it("lists the purposes a connection can be bound to", async () => {
    const purposes = [{ id: "vision" }];
    stub("get", "/ai-connections/purposes", onePage(purposes));

    expect(await aiConnectionsApi.listPurposes()).toEqual(purposes);
  });

  it("binds a purpose to a connection with a put on the bindings route", async () => {
    const seen = stub("put", "/ai-connections/bindings", {});

    await aiConnectionsApi.setBinding({
      purpose_key: "vision",
      connection_id: "c1",
    });

    expect(seen[0]).toMatchObject({
      method: "PUT",
      path: "/api/v1/ai-connections/bindings",
      body: { purpose_key: "vision", connection_id: "c1" },
    });
  });

  it("tests a key with only the five fields the endpoint allows, so the name cannot turn the test into a 422", async () => {
    const result = { ok: true };
    const seen = stub("post", "/ai-connections/test", result);
    const draft = {
      name: "Main",
      provider: "openai",
      api_key: "sk-1",
      api_base_url: "https://api.example.com",
      model_name: "m",
      capabilities: ["vision"],
      temperature: 0.2,
    } as unknown as AiConnectionDraft;

    expect(await aiConnectionsApi.test(draft)).toEqual(result);
    expect(seen[0].body).toEqual({
      provider: "openai",
      api_key: "sk-1",
      api_base_url: "https://api.example.com",
      model_name: "m",
      capabilities: ["vision"],
    });
  });
});
