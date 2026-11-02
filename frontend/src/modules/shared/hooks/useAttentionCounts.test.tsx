import React from "react";
import { renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { attentionCount, useAttentionCounts } from "./useAttentionCounts";
import { server } from "@/test/mocks/server";
import { http, HttpResponse } from "msw";

const createWrapper = () => {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
};

let requested: URL | null = null;

describe("useAttentionCounts", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    requested = null;
    server.use(
      http.get("/api/v1/items/attention-counts", ({ request }) => {
        requested = new URL(request.url);
        return HttpResponse.json({
          expired: 2,
          expiring_soon: 9,
          low_stock: 3,
        });
      }),
    );
  });

  it("reads the three shares from the one endpoint", async () => {
    const { result } = renderHook(() => useAttentionCounts(true), {
      wrapper: createWrapper(),
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual({
      expired: 2,
      expiring_soon: 9,
      low_stock: 3,
    });
    // The heading and the statistics card must count the same rows: the
    // module-data setting travels with every call.
    expect(requested?.searchParams.get("exclude_module_contexts")).toBe("true");
  });

  it("asks for module records when the setting shows them", async () => {
    renderHook(() => useAttentionCounts(false), { wrapper: createWrapper() });

    await waitFor(() => expect(requested).not.toBeNull());
    expect(requested?.searchParams.get("exclude_module_contexts")).toBe(
      "false",
    );
  });
});

describe("attentionCount", () => {
  it("is the rows the list opens with, not the shares summed", () => {
    // Three short products held as six records: their sum said 14 over 17.
    expect(
      attentionCount({
        expired: 2,
        expiring_soon: 9,
        low_stock: 3,
        records: 17,
      }),
    ).toBe(17);
  });

  it("reads a missing answer as zero, never a crash", () => {
    expect(attentionCount(undefined)).toBe(0);
  });
});
