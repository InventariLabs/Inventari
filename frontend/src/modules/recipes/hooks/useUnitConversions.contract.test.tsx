import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, waitFor, act } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { recordRequests } from "@/test/requestLog";
import { onePage } from "@/test/mocks/page";
import {
  useCreateUnitConversion,
  useDeleteUnitConversion,
  useUnitConversions,
  useUpdateUnitConversion,
} from "./useUnitConversions";

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

const modules = vi.hoisted(() => ({ enabled: true }));
vi.mock("@/contexts/ModulesContext", () => ({
  useModules: () => ({
    isLoading: false,
    isModuleEnabled: () => modules.enabled,
  }),
}));

let client: QueryClient;
const wrapper = ({ children }: { children: ReactNode }) => (
  <QueryClientProvider client={client}>{children}</QueryClientProvider>
);

beforeEach(() => {
  modules.enabled = true;
  client = new QueryClient();
});

/**
 * Unit conversions ("1 cup of flour = 120 g") are read in the language of the
 * screen and written one row at a time.
 */
describe("unit conversion hooks", () => {
  it("lists the conversions in the language asked for", async () => {
    const log = recordRequests(() => onePage([{ id: "u1" }]));
    const { result } = renderHook(() => useUnitConversions("pl"), { wrapper });
    await waitFor(() => expect(result.current.data).toEqual([{ id: "u1" }]));
    expect(log[0]).toMatchObject({
      method: "GET",
      path: "/recipes/unit-conversions",
      query: { lang: "pl" },
    });
  });

  it("defaults to English", async () => {
    const log = recordRequests(() => onePage([]));
    renderHook(() => useUnitConversions(), { wrapper });
    await waitFor(() => expect(log).toHaveLength(1));
    expect(log[0].query.lang).toBe("en");
  });

  it("asks nothing of an organization without the recipes module", async () => {
    modules.enabled = false;
    const log = recordRequests();
    const { result } = renderHook(() => useUnitConversions(), { wrapper });
    await new Promise((r) => setTimeout(r, 20));
    expect(result.current.fetchStatus).toBe("idle");
    expect(log).toHaveLength(0);
  });

  it("creates, updates and deletes by the row's own path", async () => {
    const log = recordRequests(() => ({}));
    const create = renderHook(() => useCreateUnitConversion(), { wrapper });
    const update = renderHook(() => useUpdateUnitConversion(), { wrapper });
    const del = renderHook(() => useDeleteUnitConversion(), { wrapper });
    await act(() =>
      create.result.current.mutateAsync({ unit: "cup" } as never),
    );
    await act(() =>
      update.result.current.mutateAsync({
        id: "u1",
        data: { grams: 120 } as never,
      }),
    );
    await act(() => del.result.current.mutateAsync("u1"));
    expect(log.map((r) => [r.method, r.path, r.body])).toEqual([
      ["POST", "/recipes/unit-conversions", { unit: "cup" }],
      ["PUT", "/recipes/unit-conversions/u1", { grams: 120 }],
      ["DELETE", "/recipes/unit-conversions/u1", undefined],
    ]);
  });

  it("reads the list again after a write", async () => {
    recordRequests(() => onePage([]));
    const list = renderHook(() => useUnitConversions("en"), { wrapper });
    await waitFor(() => expect(list.result.current.isSuccess).toBe(true));
    const log = recordRequests(() => onePage([{ id: "u2" }]));
    const create = renderHook(() => useCreateUnitConversion(), { wrapper });
    await act(() =>
      create.result.current.mutateAsync({ unit: "cup" } as never),
    );
    await waitFor(() => expect(log.some((r) => r.method === "GET")).toBe(true));
  });
});
