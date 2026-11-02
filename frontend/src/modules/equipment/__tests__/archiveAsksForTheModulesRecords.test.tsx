/**
 * The Archive tab has to ask for the module's records, not for its category.
 *
 * `context_tag=equipment` asks the category alone, so every asset saved
 * without one — the form has never required a category — dropped out of the
 * tab the moment it was archived: 60 rows archived by a bulk action, 0 of
 * them in the tab that is supposed to hold them, and no way to restore them
 * from inside the module. `module_scope` asks the pair of questions the
 * active list asks.
 */
import type { ReactNode } from "react";
import { renderHook, waitFor } from "@testing-library/react";
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

describe("equipment archive scope", () => {
  beforeEach(() => {
    signInWith(["items.read"]);
  });
  afterEach(() => signOut());

  it("asks /items/archived for everything the module owns", async () => {
    let asked: URL | null = null;
    server.use(
      http.get("/api/v1/equipment/assets", () =>
        HttpResponse.json({ items: [], total: 0, offset: 0, limit: 50 }),
      ),
      http.get("/api/v1/items/archived", ({ request }) => {
        asked = new URL(request.url);
        return HttpResponse.json({ items: [], total: 0, offset: 0, limit: 50 });
      }),
    );

    renderHook(() => useAssetListActions(), { wrapper });

    await waitFor(() => expect(asked).not.toBeNull());
    const params = (asked as unknown as URL).searchParams;
    expect(params.get("module_scope")).toBe("equipment");
    expect(params.get("context_tag")).toBeNull();
  });
});
