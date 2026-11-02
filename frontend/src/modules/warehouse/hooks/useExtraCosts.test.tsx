import React from "react";
import { describe, expect, it, vi } from "vitest";
import { act, renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import { server } from "@/test/mocks/server";
import {
  useAddExtraCost,
  useExtraCosts,
  useRemoveExtraCost,
} from "./useExtraCosts";

function setup() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const invalidated: unknown[] = [];
  vi.spyOn(client, "invalidateQueries").mockImplementation(async (filters) => {
    invalidated.push(filters?.queryKey);
  });
  const wrapper = ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  return { invalidated, wrapper };
}

const VIEW = { costs: [], lines: [] };

/**
 * Freight and duty on a receipt. A cost added or removed without dropping
 * the receipt's cost view left the landed prices per line as they were
 * before the change.
 */
describe("receipt extra costs — read, added and removed per document", () => {
  it("does not ask for the costs of a receipt not chosen yet, or when turned off", () => {
    const { wrapper } = setup();

    const none = renderHook(() => useExtraCosts(""), { wrapper });
    const off = renderHook(() => useExtraCosts("doc-1", false), { wrapper });

    expect(none.result.current.fetchStatus).toBe("idle");
    expect(off.result.current.fetchStatus).toBe("idle");
  });

  it("reads the receipt's costs", async () => {
    server.use(
      http.get("*/warehouse/documents/doc-1/extra-costs", () =>
        HttpResponse.json(VIEW),
      ),
    );
    const { wrapper } = setup();
    const { result } = renderHook(() => useExtraCosts("doc-1"), { wrapper });

    await waitFor(() => expect(result.current.data).toEqual(VIEW));
  });

  it("adds and removes a cost, refreshing that receipt's costs each time", async () => {
    const seen: string[] = [];
    server.use(
      http.post(
        "*/warehouse/documents/doc-1/extra-costs",
        async ({ request }) => {
          seen.push(`POST ${JSON.stringify(await request.json())}`);
          return HttpResponse.json(VIEW);
        },
      ),
      http.delete(
        "*/warehouse/documents/doc-1/extra-costs/:costId",
        ({ params }) => {
          seen.push(`DELETE ${String(params.costId)}`);
          return HttpResponse.json(VIEW);
        },
      ),
    );
    const { invalidated, wrapper } = setup();
    const { result } = renderHook(
      () => ({
        add: useAddExtraCost("doc-1"),
        remove: useRemoveExtraCost("doc-1"),
      }),
      { wrapper },
    );

    await act(() =>
      result.current.add.mutateAsync({
        kind: "FREIGHT",
        amount: "40.00",
        allocation_method: "BY_VALUE",
      } as never),
    );
    await act(() => result.current.remove.mutateAsync("cost-1"));

    expect(seen).toEqual([
      'POST {"kind":"FREIGHT","amount":"40.00","allocation_method":"BY_VALUE"}',
      "DELETE cost-1",
    ]);
    expect(invalidated).toEqual([
      ["document-extra-costs", "doc-1"],
      ["document-extra-costs", "doc-1"],
    ]);
  });
});
