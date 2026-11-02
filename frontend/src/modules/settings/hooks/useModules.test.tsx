import React from "react";
import { renderHook, waitFor, act } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter } from "react-router-dom";
import { describe, it, expect, vi, beforeEach } from "vitest";
import {
  useMyModules,
  useAvailableModules,
  useToggleModule,
  useFocusModule,
} from "./useModules";
import { server } from "@/test/mocks/server";
import { http, HttpResponse } from "msw";
import { onePage } from "@/test/mocks/page";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

const createWrapper = () => {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>{children}</BrowserRouter>
    </QueryClientProvider>
  );
};

describe("useMyModules", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    server.use(
      http.get("/api/v1/modules/my", () =>
        HttpResponse.json(["stats", "recipes"]),
      ),
    );
  });

  it("returns enabled module names", async () => {
    const { result } = renderHook(() => useMyModules(), {
      wrapper: createWrapper(),
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toContain("stats");
  });

  it("returns error on API failure", async () => {
    server.use(
      http.get("/api/v1/modules/my", () =>
        HttpResponse.json({ detail: "Error" }, { status: 500 }),
      ),
    );
    const { result } = renderHook(() => useMyModules(), {
      wrapper: createWrapper(),
    });
    await waitFor(() => expect(result.current.isError).toBe(true));
  });
});

describe("useAvailableModules", () => {
  beforeEach(() => {
    server.use(
      http.get("/api/v1/modules/available", () =>
        HttpResponse.json(
          onePage([
            { name: "stats", display_name: "Statistics", is_enabled: true },
            { name: "recipes", display_name: "Recipes", is_enabled: false },
          ]),
        ),
      ),
    );
  });

  it("returns available module info", async () => {
    const { result } = renderHook(() => useAvailableModules(), {
      wrapper: createWrapper(),
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toHaveLength(2);
  });
});

describe("useToggleModule", () => {
  beforeEach(() => {
    server.use(
      http.post("/api/v1/modules/toggle", () =>
        HttpResponse.json({ name: "stats", is_enabled: false }),
      ),
      http.get("/api/v1/modules/my", () => HttpResponse.json(["recipes"])),
    );
  });

  it("toggles a module", async () => {
    const { result } = renderHook(() => useToggleModule(), {
      wrapper: createWrapper(),
    });
    act(() => result.current.mutate({ moduleName: "stats", enabled: false }));
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
  });
});

describe("useFocusModule", () => {
  it("names the focused module while focus mode is applied", async () => {
    server.use(
      http.get("/api/v1/modules/focus", () =>
        HttpResponse.json({
          applied: true,
          focus_module: "equipment",
          enabled_modules: ["core", "equipment"],
          diff: null,
        }),
      ),
    );
    const { result } = renderHook(() => useFocusModule(), {
      wrapper: createWrapper(),
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.focusModule).toBe("equipment");
  });

  it("stays null when focus mode is not applied", async () => {
    server.use(
      http.get("/api/v1/modules/focus", () =>
        HttpResponse.json({
          applied: false,
          focus_module: null,
          enabled_modules: ["core", "items"],
          diff: null,
        }),
      ),
    );
    const { result } = renderHook(() => useFocusModule(), {
      wrapper: createWrapper(),
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.focusModule).toBeNull();
  });
});
