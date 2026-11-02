import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, waitFor, act } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import type { ReactNode } from "react";
import { server } from "@/test/mocks/server";
import { onePage } from "@/test/mocks/page";
import { queryKeys } from "@/hooks/queries/keys";
import type { AiPurpose } from "@/types/ai";
import {
  isVisionConfigured,
  useAiConnections,
  useAiPurposes,
  useCreateAiConnection,
  useDeleteAiConnection,
  useSetAiBinding,
  useTestAiConnection,
  useUpdateAiConnection,
} from "./useAiConnections";

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

function makeWrapper(client: QueryClient) {
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
}

const newClient = () =>
  new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });

const purpose = (over: Partial<AiPurpose>): AiPurpose =>
  ({
    key: "vision.extract",
    usable: true,
    bound_connection_id: null,
    ...over,
  }) as AiPurpose;

/**
 * Whether the image automation "works" is the registry's `usable` verdict
 * for that one purpose. Reading the raw binding instead would promise a
 * feature the server will refuse.
 */
describe("isVisionConfigured", () => {
  it("is false before the registry has answered", () => {
    expect(isVisionConfigured(undefined)).toBe(false);
  });

  it("is true only for a usable vision.extract purpose", () => {
    expect(isVisionConfigured([purpose({})])).toBe(true);
    expect(isVisionConfigured([purpose({ usable: false })])).toBe(false);
    expect(isVisionConfigured([purpose({ key: "other.purpose" })])).toBe(false);
  });

  it("ignores a binding that is chosen but not usable", () => {
    expect(
      isVisionConfigured([
        purpose({ usable: false, bound_connection_id: "c1" }),
      ]),
    ).toBe(false);
  });
});

describe("AI connection queries", () => {
  it("lists connections and purposes", async () => {
    server.use(
      http.get("/api/v1/ai-connections/purposes", () =>
        HttpResponse.json(onePage([{ key: "vision.extract" }])),
      ),
      http.get("/api/v1/ai-connections", () =>
        HttpResponse.json(onePage([{ id: "c1" }])),
      ),
    );
    const client = newClient();
    const conns = renderHook(() => useAiConnections(), {
      wrapper: makeWrapper(client),
    });
    const purposes = renderHook(() => useAiPurposes(), {
      wrapper: makeWrapper(client),
    });
    await waitFor(() => expect(conns.result.current.isSuccess).toBe(true));
    await waitFor(() => expect(purposes.result.current.isSuccess).toBe(true));
    expect(conns.result.current.data).toEqual([{ id: "c1" }]);
    expect(purposes.result.current.data).toEqual([{ key: "vision.extract" }]);
  });
});

describe("AI connection mutations", () => {
  beforeEach(() => vi.clearAllMocks());

  it("creates, updates and deletes against the connection's own path", async () => {
    const calls: string[] = [];
    server.use(
      http.post("/api/v1/ai-connections", () => {
        calls.push("create");
        return HttpResponse.json({ id: "c1" });
      }),
      http.put("/api/v1/ai-connections/c1", async ({ request }) => {
        calls.push(`update:${JSON.stringify(await request.json())}`);
        return HttpResponse.json({ id: "c1" });
      }),
      http.delete("/api/v1/ai-connections/c1", () => {
        calls.push("delete");
        return new HttpResponse(null, { status: 204 });
      }),
    );
    const wrapper = makeWrapper(newClient());
    const create = renderHook(() => useCreateAiConnection(), { wrapper });
    const update = renderHook(() => useUpdateAiConnection(), { wrapper });
    const del = renderHook(() => useDeleteAiConnection(), { wrapper });

    await act(() => create.result.current.mutateAsync({ name: "n" } as never));
    await act(() =>
      update.result.current.mutateAsync({
        id: "c1",
        data: { model_name: "m" } as never,
      }),
    );
    await act(() => del.result.current.mutateAsync("c1"));
    expect(calls).toEqual(["create", 'update:{"model_name":"m"}', "delete"]);
  });

  it("sends only the fields the test endpoint accepts", async () => {
    let body: Record<string, unknown> = {};
    server.use(
      http.post("/api/v1/ai-connections/test", async ({ request }) => {
        body = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json({ ok: true });
      }),
    );
    const { result } = renderHook(() => useTestAiConnection(), {
      wrapper: makeWrapper(newClient()),
    });
    await act(() =>
      result.current.mutateAsync({
        name: "baggage",
        provider: "openai",
        api_key: "k",
        api_base_url: null,
        model_name: "m",
        capabilities: ["vision"],
      } as never),
    );
    expect(Object.keys(body).sort()).toEqual([
      "api_base_url",
      "api_key",
      "capabilities",
      "model_name",
      "provider",
    ]);
  });

  it("shows the chosen connection at once and keeps it when the save succeeds", async () => {
    server.use(
      http.put("/api/v1/ai-connections/bindings", () => HttpResponse.json({})),
    );
    const client = newClient();
    client.setQueryDefaults(queryKeys.aiConnections.purposes, {
      gcTime: Infinity,
    });
    client.setQueryData(queryKeys.aiConnections.purposes, [
      purpose({ key: "vision.extract", bound_connection_id: "old" }),
      purpose({ key: "text.parse", bound_connection_id: "keep" }),
    ]);
    const { result } = renderHook(() => useSetAiBinding(), {
      wrapper: makeWrapper(client),
    });
    await act(() =>
      result.current.mutateAsync({
        purpose_key: "vision.extract",
        connection_id: "new",
      } as never),
    );
    const cached = client.getQueryData<AiPurpose[]>(
      queryKeys.aiConnections.purposes,
    );
    expect(
      cached?.find((p) => p.key === "vision.extract")?.bound_connection_id,
    ).toBe("new");
    expect(
      cached?.find((p) => p.key === "text.parse")?.bound_connection_id,
    ).toBe("keep");
  });

  it("puts the previous binding back when the save is refused", async () => {
    server.use(
      http.put("/api/v1/ai-connections/bindings", () =>
        HttpResponse.json({ detail: "no" }, { status: 422 }),
      ),
      // The refetch the invalidation schedules must not repaint the cache.
      http.get("/api/v1/ai-connections/purposes", () => new Promise(() => {})),
    );
    const client = newClient();
    client.setQueryDefaults(queryKeys.aiConnections.purposes, {
      gcTime: Infinity,
    });
    client.setQueryData(queryKeys.aiConnections.purposes, [
      purpose({ key: "vision.extract", bound_connection_id: "old" }),
    ]);
    const { result } = renderHook(() => useSetAiBinding(), {
      wrapper: makeWrapper(client),
    });
    await act(async () => {
      await result.current
        .mutateAsync({
          purpose_key: "vision.extract",
          connection_id: "new",
        } as never)
        .catch(() => undefined);
    });
    const cached = client.getQueryData<AiPurpose[]>(
      queryKeys.aiConnections.purposes,
    );
    expect(cached?.[0].bound_connection_id).toBe("old");
  });
});
