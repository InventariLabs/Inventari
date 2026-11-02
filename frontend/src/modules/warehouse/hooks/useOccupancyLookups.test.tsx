import * as React from "react";
import { renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, describe, expect, it, vi } from "vitest";

import { putawayOccupancyApi } from "@/modules/warehouse/api/putaway";
import { useShelfEntries } from "./useOccupancyLookups";

vi.mock("@/modules/warehouse/api/putaway", () => ({
  putawayOccupancyApi: { get: vi.fn() },
}));

function wrapper({ children }: { children: React.ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

afterEach(() => vi.restoreAllMocks());

describe("useShelfEntries", () => {
  it("reads a shelf that is both opened and picked once, without a duplicate-query warning", async () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    vi.mocked(putawayOccupancyApi.get).mockResolvedValue({
      locations: [{ location_id: "shelf-a", entries: [] }],
    } as never);

    const { result } = renderHook(
      () => useShelfEntries(["shelf-a", "shelf-b", "shelf-a"]),
      { wrapper },
    );

    await waitFor(() =>
      expect(result.current.entries.has("shelf-a")).toBe(true),
    );
    expect(putawayOccupancyApi.get).toHaveBeenCalledTimes(2);
    expect(warn).not.toHaveBeenCalledWith(
      expect.stringContaining("Duplicate Queries"),
    );
  });
});
