/**
 * The Archive tab's search has to reach the request.
 *
 * The toolbar shows one search box on both tabs, but the archived query sent
 * only `module_scope`, `offset` and `limit`: typing "Asset" over the archive
 * re-asked for the same first page, so the filter the box promises did not
 * exist. `/items/archived` has accepted `search` all along (name, brand,
 * barcode, label code).
 */
import type { ReactNode } from "react";
import { act, renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { http, HttpResponse } from "msw";

import { server } from "@/test/mocks/server";
import { signInWith, signOut } from "@/test/auth";
import { useAssetListActions } from "../hooks/useAssetListActions";

vi.mock("@/contexts/ModulesContext", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/contexts/ModulesContext")>()),
  useModules: () => ({
    enabledModules: ["equipment"],
    isModuleEnabled: () => true,
    isLoading: false,
    refreshModules: vi.fn(),
  }),
}));

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return (
    <MemoryRouter>
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    </MemoryRouter>
  );
}

describe("equipment archive search", () => {
  beforeEach(() => {
    signInWith(["items.read"]);
  });
  afterEach(() => signOut());

  it("asks the archive for the phrase typed over it", async () => {
    const asked: URL[] = [];
    server.use(
      http.get("/api/v1/equipment/assets", () =>
        HttpResponse.json({ items: [], total: 0, offset: 0, limit: 50 }),
      ),
      http.get("/api/v1/items/archived", ({ request }) => {
        asked.push(new URL(request.url));
        return HttpResponse.json({ items: [], total: 0, offset: 0, limit: 50 });
      }),
    );

    const { result } = renderHook(() => useAssetListActions(), { wrapper });
    await waitFor(() => expect(asked.length).toBeGreaterThan(0));

    act(() => result.current.setListTab("archived"));
    act(() => result.current.setSearch("Asset"));

    await waitFor(() =>
      expect(
        asked.some((url) => url.searchParams.get("search") === "Asset"),
      ).toBe(true),
    );
    const filtered = asked.filter(
      (url) => url.searchParams.get("search") === "Asset",
    );
    expect(filtered.at(-1)?.searchParams.get("module_scope")).toBe("equipment");
  });
});
