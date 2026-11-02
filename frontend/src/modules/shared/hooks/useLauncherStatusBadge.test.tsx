/**
 * A badge is a question about a module's data. While the organization's
 * module list is still loading, the launcher only holds the default
 * install's guess — asking the endpoint then bought a 403 on the onboarding
 * screen.
 */
import { describe, it, expect, beforeEach } from "vitest";
import { act, renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import axios from "axios";
import { http, HttpResponse } from "msw";
import * as React from "react";

import { server } from "@/test/mocks/server";
import { ModulesProvider } from "@/contexts/ModulesContext";
import { useAuthStore } from "@/store/authStore";
import { useLauncherStatusBadge } from "./useLauncherStatusBadge";

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

function renderBadge() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const view = renderHook(
    () =>
      useLauncherStatusBadge({
        queryKey: ["badge-test"],
        queryFn: async () => {
          const response = await axios.get<{ count: number }[]>(
            "/api/v1/badge-source",
          );
          return response.data;
        },
        labelKey: "badgeTest",
        labelNs: "common",
        staleTime: 0,
        refetchInterval: 60_000,
        extractCount: (data) => data.length,
      }),
    {
      wrapper: ({ children }: { children: React.ReactNode }) => (
        <QueryClientProvider client={client}>
          <ModulesProvider>{children}</ModulesProvider>
        </QueryClientProvider>
      ),
    },
  );
  return { ...view, client };
}

beforeEach(() => {
  useAuthStore.setState({ isAuthenticated: true, isLoading: false });
  server.resetHandlers();
});

describe("useLauncherStatusBadge", () => {
  it("asks nothing while the organization's module list is still loading", async () => {
    let sourceRequested = 0;
    let releaseModules!: () => void;
    const held = new Promise<void>((resolve) => {
      releaseModules = resolve;
    });
    server.use(
      http.get("/api/v1/modules/my", async () => {
        await held;
        return HttpResponse.json(["core", "items"]);
      }),
      http.get("/api/v1/badge-source", () => {
        sourceRequested += 1;
        return HttpResponse.json([{ id: "alert-1" }]);
      }),
    );

    const { result } = renderBadge();
    // The provider's own focus query settles in this window; keep it inside
    // act so its re-render is not a stray warning.
    await act(async () => {
      await sleep(50);
    });

    // The module list is a guess at this point; the badge waits for the
    // organization's own answer instead of asking on the guess.
    expect(sourceRequested).toBe(0);

    await act(async () => {
      releaseModules();
    });
    // Waiting for the badge itself (not just the request) keeps the query's
    // resolution inside the act wrapper.
    await waitFor(() => expect(result.current).not.toBeNull());
    expect(sourceRequested).toBe(1);
  });

  it("reports a failed read instead of vanishing", async () => {
    server.use(
      http.get("/api/v1/modules/my", () =>
        HttpResponse.json(["core", "items"]),
      ),
      http.get("/api/v1/badge-source", () =>
        HttpResponse.json({ detail: "boom" }, { status: 500 }),
      ),
    );

    const { result } = renderBadge();

    await waitFor(() => expect(result.current?.failed).toBe(true));
    expect(result.current?.count).toBe(0);
  });

  it("reports a failed refresh even when an earlier read is cached", async () => {
    let fail = false;
    server.use(
      http.get("/api/v1/modules/my", () =>
        HttpResponse.json(["core", "items"]),
      ),
      http.get("/api/v1/badge-source", () =>
        fail
          ? HttpResponse.json({ detail: "boom" }, { status: 500 })
          : HttpResponse.json([]),
      ),
    );

    const { result, client } = renderBadge();
    await waitFor(() =>
      expect(client.getQueryState(["badge-test"])?.status).toBe("success"),
    );
    expect(result.current).toBeNull();

    fail = true;
    await act(async () => {
      await client.refetchQueries({ queryKey: ["badge-test"] });
    });

    await waitFor(() => expect(result.current?.failed).toBe(true));
  });
});
