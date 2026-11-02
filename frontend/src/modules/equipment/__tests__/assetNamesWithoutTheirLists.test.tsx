import React from "react";
import { renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { describe, it, expect } from "vitest";
import { http, HttpResponse } from "msw";
import { server } from "@/test/mocks/server";
import { ModulesProvider } from "@/contexts/ModulesContext";
import { useAssetImage } from "../hooks/useAssetImage";
import { useLocationLabel } from "../hooks/useLocationLabel";
import type { Item } from "@/types";

/**
 * Both hooks only decorate a row with something looked up in a list. A list
 * that failed leaves the row as it came — the placeholder picture, the name
 * the API sent — and claims nothing about the organization.
 *
 * Behaviour documents, not teeth: with the lookup dropped the row comes back
 * exactly like this, so both tests pass either way. What they pin is that a
 * failure adds no claim of its own — no invented picture, no invented name.
 */
function wrapper({ children }: { children: React.ReactNode }) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return (
    <QueryClientProvider client={queryClient}>
      <ModulesProvider>
        <MemoryRouter>{children}</MemoryRouter>
      </ModulesProvider>
    </QueryClientProvider>
  );
}

const failing = (path: string) =>
  http.get(path, () => HttpResponse.json({ detail: "boom" }, { status: 500 }));

describe("useLocationLabel — the locations list failed", () => {
  it("keeps the name the API sent", async () => {
    server.use(failing("/api/v1/locations"));
    const { result } = renderHook(() => useLocationLabel(["loc-1"]), {
      wrapper,
    });

    await waitFor(() =>
      expect(result.current("loc-1", "Server room")).toBe("Server room"),
    );
    expect(result.current("loc-1", null)).toBeNull();
  });
});

describe("useAssetImage — the models list failed", () => {
  it("gives a unit with its own picture that picture, and the rest none", async () => {
    server.use(failing("/api/v1/equipment/models"));
    const { result } = renderHook(() => useAssetImage(), { wrapper });

    const own = { image_url: "/own.png" } as unknown as Item;
    const bare = {
      metadata: { equipment: { model_id: "m1" } },
    } as unknown as Item;
    await waitFor(() =>
      expect(result.current(own)).toEqual({
        url: "/own.png",
        fromModel: false,
      }),
    );
    expect(result.current(bare)).toBeNull();
  });
});
