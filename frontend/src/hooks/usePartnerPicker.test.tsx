import type { ReactNode } from "react";
import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { server } from "@/test/mocks/server";
import { SUPPLIER_ROLE_TYPES } from "@/hooks/partnerRoles";
import { usePartnerPicker } from "./usePartnerPicker";

vi.mock("@/contexts/ModulesContext", () => ({
  useModules: () => ({ isModuleEnabled: () => true, isLoading: false }),
}));

// An organization with more partners than any one page: "Supplier 001" …
// "Supplier 250", and one customer-only record outside the supplier role set.
const REGISTER = Array.from({ length: 250 }, (_, i) => ({
  id: `p-${i + 1}`,
  name: `Supplier ${String(i + 1).padStart(3, "0")}`,
  type: "SUPPLIER",
  is_active: true,
}));
const CUSTOMER = {
  id: "c-1",
  name: "Customer only",
  type: "CUSTOMER",
  is_active: true,
};

function serveRegister(requests: URLSearchParams[] = []) {
  server.use(
    http.get("/api/v1/partners", ({ request }) => {
      const params = new URL(request.url).searchParams;
      requests.push(params);
      const search = (params.get("search") ?? "").toLowerCase();
      const limit = Number(params.get("limit") ?? 100);
      const hits = REGISTER.filter((p) =>
        p.name.toLowerCase().includes(search),
      );
      return HttpResponse.json({
        items: hits.slice(0, limit),
        total: hits.length,
      });
    }),
    http.get("/api/v1/partners/:id", ({ params }) => {
      const found = [...REGISTER, CUSTOMER].find((p) => p.id === params.id);
      return found
        ? HttpResponse.json(found)
        : HttpResponse.json({ detail: "gone" }, { status: 404 });
    }),
  );
}

let queryClient: QueryClient;

function QueryWrapper({ children }: { children: ReactNode }) {
  return (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
}

describe("usePartnerPicker", () => {
  beforeEach(() => {
    queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
  });

  // A case can pass while a read is still on its way — the slow by-id read
  // below, or a search page behind rows already on screen. Under a loaded
  // full run the last of them was answered after the file's environment had
  // gone, and the run failed on "ProgressEvent is not defined". Unmounted
  // first, so a pending debounce asks for nothing more.
  afterEach(async () => {
    cleanup();
    await waitFor(() => expect(queryClient.isFetching()).toBe(0));
  });

  it("finds the 250th partner by asking the server, not by loading them all", async () => {
    const requests: URLSearchParams[] = [];
    serveRegister(requests);
    const { result } = renderHook(() => usePartnerPicker(SUPPLIER_ROLE_TYPES), {
      wrapper: QueryWrapper,
    });

    await waitFor(() =>
      expect(result.current.options.length).toBeGreaterThan(0),
    );
    expect(result.current.options.map((o) => o.name)).not.toContain(
      "Supplier 250",
    );

    act(() => result.current.setSearch("Supplier 250"));
    await waitFor(() =>
      expect(result.current.options.map((o) => o.name)).toEqual([
        "Supplier 250",
      ]),
    );
    expect(requests.at(-1)?.get("search")).toBe("Supplier 250");
    expect(requests.at(-1)?.getAll("types")).toEqual([...SUPPLIER_ROLE_TYPES]);
    expect(requests.at(-1)?.get("is_active")).toBe("true");
  });

  it("is loading, not empty, while typed text has not reached the server", async () => {
    serveRegister();
    const { result } = renderHook(() => usePartnerPicker(SUPPLIER_ROLE_TYPES), {
      wrapper: QueryWrapper,
    });
    await waitFor(() => expect(result.current.loading).toBe(false));

    act(() => result.current.setSearch("Supplier 2"));
    expect(result.current.loading).toBe(true);
    await waitFor(() => expect(result.current.loading).toBe(false));
  });

  it("names a chosen partner that is not on the first page, while nothing is typed", async () => {
    serveRegister();
    const { result } = renderHook(
      () => usePartnerPicker(SUPPLIER_ROLE_TYPES, "p-250"),
      { wrapper: QueryWrapper },
    );

    await waitFor(() => expect(result.current.selectedOffered).toBe(true));
    expect(result.current.options[0]).toMatchObject({ name: "Supplier 250" });

    act(() => result.current.setSearch("Supplier 001"));
    await waitFor(() =>
      expect(result.current.options.map((o) => o.name)).toEqual([
        "Supplier 001",
      ]),
    );
  });

  it("keeps naming a partner picked from a search while its own read is on the way", async () => {
    serveRegister();
    // The by-id read is slow: the window the field used to read its placeholder in.
    server.use(
      http.get("/api/v1/partners/:id", async ({ params }) => {
        await new Promise((resolve) => setTimeout(resolve, 150));
        const found = REGISTER.find((p) => p.id === params.id);
        return HttpResponse.json(found);
      }),
    );
    const { result, rerender } = renderHook(
      ({ chosen }: { chosen?: string }) =>
        usePartnerPicker(SUPPLIER_ROLE_TYPES, chosen),
      { wrapper: QueryWrapper, initialProps: {} as { chosen?: string } },
    );

    act(() => result.current.setSearch("Supplier 250"));
    await waitFor(() =>
      expect(result.current.options.map((o) => o.name)).toEqual([
        "Supplier 250",
      ]),
    );
    rerender({ chosen: "p-250" });
    // The panel closes: the typed query goes, the search page with it.
    act(() => result.current.setSearch(""));

    await waitFor(() =>
      expect(result.current.options.length).toBeGreaterThan(1),
    );
    expect(result.current.options[0]).toMatchObject({ name: "Supplier 250" });
  });

  it("says a chosen partner outside the role set is not offered", async () => {
    serveRegister();
    const { result } = renderHook(
      () => usePartnerPicker(SUPPLIER_ROLE_TYPES, "c-1"),
      { wrapper: QueryWrapper },
    );

    await waitFor(() => expect(result.current.selectedOffered).toBe(false));
    expect(result.current.options.map((o) => o.id)).not.toContain("c-1");
  });

  it("reports a failed read instead of an empty register, and lists the partners after a retry", async () => {
    serveRegister();
    let failNext = true;
    server.use(
      http.get("/api/v1/partners", () => {
        if (failNext) {
          failNext = false;
          return HttpResponse.json({ detail: "boom" }, { status: 500 });
        }
        return HttpResponse.json({ items: REGISTER.slice(0, 3), total: 3 });
      }),
    );
    const { result } = renderHook(() => usePartnerPicker(SUPPLIER_ROLE_TYPES), {
      wrapper: QueryWrapper,
    });
    await waitFor(() => expect(result.current.error).not.toBeNull());
    expect(result.current.options).toEqual([]);

    act(() => result.current.retry());

    await waitFor(() => expect(result.current.options).toHaveLength(3));
    expect(result.current.error).toBeNull();
  });
});
